// 解压"增量追加写"的 .zstd 日志文件（.zstd → .jsonl）。
//
// 两个坑：
//   1) 子 agent 的结论只存在它们的会话记录里（一次性 fan-out 被 kill 时聚合结果就丢了）；
//   2) 这类日志是**增量追加**写的，一个 .zstd 里是**多个 zstd 帧首尾相接**，
//      而 Node 的 zstdDecompressSync 只解第一帧 —— 直接解只能拿到文件头那 300 字节左右。
//      所以这里按 zstd 魔数 0x28B52FFD 切帧，逐帧解再拼起来。
//
// 用法: node unzstd.js <in.zstd> <out.jsonl>
const fs = require("fs");
const zlib = require("zlib");

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

function splitFrames(buf) {
  const starts = [];
  let i = 0;
  while (i <= buf.length - 4) {
    const j = buf.indexOf(MAGIC, i);
    if (j < 0) break;
    starts.push(j);
    i = j + 4;
  }
  if (!starts.length) return [buf];
  const out = [];
  for (let k = 0; k < starts.length; k++) {
    const end = k + 1 < starts.length ? starts[k + 1] : buf.length;
    out.push(buf.subarray(starts[k], end));
  }
  return out;
}

const [, , src, dst] = process.argv;
if (!src || !dst) {
  console.error("用法: node unzstd.js <in.zstd> <out.jsonl>");
  process.exit(2);
}
const buf = fs.readFileSync(src);
const frames = splitFrames(buf);
const chunks = [];
let ok = 0, bad = 0;
for (const fr of frames) {
  try {
    chunks.push(zlib.zstdDecompressSync(fr));
    ok++;
  } catch (e) {
    bad++;
  }
}
const out = Buffer.concat(chunks);
fs.writeFileSync(dst, out);
console.log(`${src} -> ${dst}  ${buf.length} -> ${out.length} bytes  (帧 ${frames.length}: ok ${ok} bad ${bad})`);
