// TinyTTS helper, same protocol as synth.py: node synth_tiny.js MODEL SPEED, or
// node synth_tiny.js --serve SOCKET MODEL SPEED (stays resident, one connection per reply).
// Reads one sentence per line on stdin (or the connection). Writes: the sample rate (u32), then for
// each sentence a frame: byte count (u32), seconds spent synthesizing it (f32), raw s16le PCM.
// Loading the model takes ~14 s on the N3350, hence the resident mode; it exits after IDLE_MS unused.
const path = require("path");
const readline = require("readline");

const RATE = 44100;
const realLog = console.log;
console.log = (...a) => console.error(...a);   // the library chatters; stdout is the PCM channel
const TinyTTS = require(path.join(__dirname, "tiny", "node_modules", "tiny-tts"));

try { process.title = "claude-voice"; } catch (e) {}

function u32(n) { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; }
function f32(x) { const b = Buffer.alloc(4); b.writeFloatLE(x); return b; }

function floatWavToS16(raw) {
  const wav = Buffer.from(raw.buffer, raw.byteOffset, raw.byteLength);
  const at = wav.indexOf("data");
  const len = wav.readUInt32LE(at + 4);
  const n = Math.min(len, wav.length - at - 8) >> 2;
  const out = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, wav.readFloatLE(at + 8 + i * 4)));
    out.writeInt16LE(Math.round(s * 32767), i * 2);
  }
  return out;
}

const IDLE_MS = 15 * 60 * 1000;

async function synthesize(tts, speed, sentences, out, alive) {
  out.write(u32(RATE));
  for (const sentence of sentences) {
    if (!alive()) return;
    const started = Date.now();
    const wav = await tts.speak(sentence, { output: "/dev/null", speed });
    const pcm = floatWavToS16(wav);
    out.write(Buffer.concat([u32(pcm.length), f32((Date.now() - started) / 1000), pcm]));
  }
}

function serve(sock, tts, speed) {
  const fs = require("fs");
  const net = require("net");
  let chain = Promise.resolve();
  let idle;
  const bump = () => { clearTimeout(idle); idle = setTimeout(() => { try { fs.unlinkSync(sock); } catch (e) {} process.exit(0); }, IDLE_MS); };
  const server = net.createServer({ allowHalfOpen: true }, (conn) => {
    let buf = "";
    conn.on("error", () => {});
    conn.on("data", (d) => { buf += d; });
    conn.on("end", () => {
      const sentences = buf.split("\n").map((s) => s.trim()).filter(Boolean);
      chain = chain.then(() => synthesize(tts, speed, sentences, conn, () => !conn.destroyed).catch(() => {}))
                   .then(() => { conn.end(); bump(); });
    });
    bump();
  });
  server.listen(sock, bump);
  for (const sig of ["SIGTERM", "SIGINT"]) process.on(sig, () => { try { fs.unlinkSync(sock); } catch (e) {} process.exit(0); });
}

(async () => {
  const serving = process.argv[2] === "--serve";
  const args = serving ? process.argv.slice(3) : process.argv.slice(2);
  const tts = new TinyTTS({ modelPath: serving ? args[1] : args[0] });
  const speed = parseFloat(serving ? args[2] : args[1]);
  await tts.init();
  if (serving) return serve(args[0], tts, speed);
  const chunks = [];
  const rl = readline.createInterface({ input: process.stdin });
  for await (const line of rl) chunks.push(line);
  await synthesize(tts, speed, chunks.map((s) => s.trim()).filter(Boolean), process.stdout, () => true);
  await tts.dispose();
})().catch((e) => { console.error(e); process.exit(1); });
