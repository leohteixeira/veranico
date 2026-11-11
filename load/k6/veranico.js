// The load campaign of SPEC 16.5, run by k6 from its container image on the Compose
// network of the load stack. Written against k6 v2.3.0 (shared-iterations executor,
// k6/execution, handleSummary; documentation read on 2026-11-11).
//
// Everything it sends is decided before it starts: `fixtures.json` (load/fixtures.py) is
// the schedule and `profile.json` the declared campaign, thresholds included. Both
// scenarios use an iteration-count executor, so every scheduled request is sent exactly
// once and none is dropped; the iteration number selects the entry of the schedule.
//
// Environment:
//   BASE_URL  the API inside the Compose network, for example http://api:8080
//   FIXTURES  path of fixtures.json        PROFILE  path of profile.json
//   SUMMARY   path the end-of-test summary is written to, as JSON
//   API_KEY   the key of the run's workspace; sent as a bearer credential, never printed
//
// Output. One evidence line per request on the console and nothing else:
//   {"scenario","index","key_index","status","quote_id"}
// Run with `--console-output <file> --log-format raw` to get them as a JSON Lines file.
// No body, header or credential is ever logged.

import { check } from 'k6';
import exec from 'k6/execution';
import http from 'k6/http';
import { SharedArray } from 'k6/data';
import { Counter } from 'k6/metrics';

// The campaign is for the local stack only. A host that is not the Compose service or
// this machine stops the run before the first request.
const LOCAL_TARGET = /^http:\/\/(api|127\.0\.0\.1|localhost)(:\d+)?$/;
const BASE_URL = __ENV.BASE_URL || '';
if (!LOCAL_TARGET.test(BASE_URL)) {
  throw new Error('BASE_URL must be the API of the local stack, for example http://api:8080');
}
if (!__ENV.API_KEY) {
  throw new Error('API_KEY is not set');
}

const profile = JSON.parse(open(__ENV.PROFILE));
const quotes = new SharedArray('quotes', () => JSON.parse(open(__ENV.FIXTURES)).quotes);
const cells = new SharedArray('cells', () => JSON.parse(open(__ENV.FIXTURES)).cells);

const declared = profile.scenarios;
if (quotes.length !== declared.quotes.distinct_keys * declared.quotes.sends_per_key) {
  throw new Error('the quote schedule does not match the profile');
}
if (cells.length !== declared.cells.requests) {
  throw new Error('the cells schedule does not match the profile');
}

// Anything that is neither the expected answer nor back-pressure.
const unexpectedStatus = new Counter('unexpected_status');
// 429 `rate_limited`: the service refusing work it will not do. Counted, not a failure.
const backPressure = new Counter('back_pressure');

export const options = {
  scenarios: {
    quotes: {
      executor: 'shared-iterations',
      exec: 'sendQuote',
      vus: declared.quotes.virtual_users,
      iterations: quotes.length,
      maxDuration: declared.quotes.max_duration,
    },
    cells: {
      executor: 'shared-iterations',
      exec: 'getCells',
      vus: declared.cells.virtual_users,
      iterations: cells.length,
      maxDuration: declared.cells.max_duration,
    },
  },
  thresholds: profile.thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)', 'count'],
};

function evidence(scenario, entry, status, quoteId) {
  console.log(
    JSON.stringify({
      scenario: scenario,
      index: entry.index,
      key_index: entry.key_index === undefined ? null : entry.key_index,
      status: status,
      quote_id: quoteId,
    }),
  );
}

function json(response) {
  try {
    return response.json();
  } catch (_) {
    return null;
  }
}

export function sendQuote() {
  const entry = quotes[exec.scenario.iterationInTest];
  const response = http.post(`${BASE_URL}/api/v1/quotes`, JSON.stringify(entry.body), {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${__ENV.API_KEY}`,
      'Idempotency-Key': entry.key,
    },
  });
  const body = json(response);
  let quoteId = null;
  if (response.status === 200) {
    const acknowledged = check(body, {
      'an acknowledged quote carries its quote_id': (b) =>
        b !== null && typeof b.quote_id === 'string' && b.quote_id !== '',
    });
    quoteId = acknowledged ? body.quote_id : null;
  } else if (response.status === 429 && body !== null && body.code === 'rate_limited') {
    backPressure.add(1);
  } else {
    unexpectedStatus.add(1);
  }
  evidence('quotes', entry, response.status, quoteId);
}

export function getCells() {
  const entry = cells[exec.scenario.iterationInTest];
  // Public reference data: no cookie and no key.
  const response = http.get(`${BASE_URL}${entry.path}`);
  if (response.status === 200) {
    check(json(response), {
      'a cells answer carries its values': (b) => b !== null && Array.isArray(b.values),
    });
  } else {
    unexpectedStatus.add(1);
  }
  evidence('cells', entry, response.status, null);
}

export function handleSummary(data) {
  // The whole summary goes to a file for the oracle; the console keeps the evidence only.
  return { [__ENV.SUMMARY]: JSON.stringify(data, null, 1) };
}
