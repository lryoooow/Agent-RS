// Optional PNG renderer. The application does not depend on Sharp.
// node scripts/render_platform_diagrams.cjs [path/to/node_modules/sharp]
const path = require('node:path');
const sharp = process.argv[2] ? require(path.resolve(process.argv[2])) : require('sharp');
const root = path.resolve(__dirname, '../docs/diagrams');

(async () => {
  for (const name of ['agent-rs-platform-architecture', 'agent-rs-analysis-workflow']) {
    const result = await sharp(path.join(root, `${name}.svg`), { density: 144 })
      .resize({ width: 1920 })
      .png()
      .toFile(path.join(root, `${name}.png`));
    console.log(`${name}.png: ${result.width} x ${result.height}, ${result.size} bytes`);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
