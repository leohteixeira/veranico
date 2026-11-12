// Writes `tile.png`, the one map tile the end-to-end run serves for every basemap request.
// It is generated here, from nothing but the two colours below: a 256 by 256 square of flat
// ground with a faint line along two edges, so the tile grid is visible in a screenshot. It is
// not derived from any map provider's imagery.
//
// It also writes `labels.png`, a fully transparent tile of the same size: the answer to every
// place-name request, so the layer that sits over the risk layer hides nothing in a capture.
//
// Usage, from `frontend/`: node e2e/fixtures/make-tile.mjs
import { Buffer } from "node:buffer";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { deflateSync } from "node:zlib";

const SIZE = 256;
const GROUND = [222, 216, 203];
const LINE = [206, 199, 184];

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes) {
  let c = 0xffffffff;
  for (const byte of bytes) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

// One filter byte (none) and three bytes per pixel on each row.
const raw = Buffer.alloc(SIZE * (1 + SIZE * 3));
for (let y = 0; y < SIZE; y += 1) {
  for (let x = 0; x < SIZE; x += 1) {
    const colour = x === 0 || y === 0 ? LINE : GROUND;
    raw.set(colour, y * (1 + SIZE * 3) + 1 + x * 3);
  }
}

/** A PNG of 8 bits per channel, without interlace. Colour type 2 is RGB and 6 is RGBA. */
function png(colourType, rows) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(SIZE, 0);
  header.writeUInt32BE(SIZE, 4);
  header.set([8, colourType, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(rows, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

writeFileSync(join(import.meta.dirname, "tile.png"), png(2, raw));
// One filter byte and four zero bytes per pixel on each row: every pixel is transparent.
writeFileSync(join(import.meta.dirname, "labels.png"), png(6, Buffer.alloc(SIZE * (1 + SIZE * 4))));
