// Runs the fresh-hop template's app.js in plain Node with a stub DOM and
// prints what it rendered, as JSON. No browser needed, so the season logic
// can be checked wherever Node is installed.
// Usage: node render_fresh_hop.mjs <app.js> <data-page> <data.json contents>
// Invoked by tests/unit/test_fresh_hop_seasons.py.
import fs from 'node:fs';
import vm from 'node:vm';

const [appPath, page, dataJson] = process.argv.slice(2);
const elements = {};
const element = () => ({
  hidden: true,
  innerHTML: '',
  textContent: '',
  addEventListener() {},
  querySelectorAll: () => [],
});
const document = {
  body: { dataset: { page } },
  getElementById: (id) => (elements[id] ||= element()),
};
const done = Promise.resolve({ json: () => JSON.parse(dataJson) });
vm.runInNewContext(fs.readFileSync(appPath, 'utf8'), {
  document, fetch: () => done, Intl, Date, Map, Set, Number, String, Object, Promise,
});
// app.js renders in the promise chain off fetch(); let it settle.
await new Promise((resolve) => setTimeout(resolve, 0));
console.log(JSON.stringify({
  listings: elements.listings?.innerHTML ?? '',
  summary: elements.summary?.innerHTML ?? '',
  quiet: elements.quiet && !elements.quiet.hidden ? elements.quiet.innerHTML : null,
}));
