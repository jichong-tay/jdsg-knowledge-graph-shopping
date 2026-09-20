const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor() { this.value = ''; this.children = []; this.classList = {toggle(){}}; this.scrollHeight = 0; this.scrollTop = 0; this.clientHeight = 100; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  setAttribute() {}
  focus() {}
}
const nodes = new Map();
const storage = new Map();
const document = {getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); }, createElement() {return new Element();}};
const scope = {document, TextEncoder, TextDecoder, crypto: require('node:crypto').webcrypto,
  sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key,value) => storage.set(key,value)},
  WebSocket: {OPEN: 1}, console, setTimeout, clearTimeout, setInterval, clearInterval};
scope.window = scope;
scope.addEventListener = () => {};
let source = fs.readFileSync('src/shopping/web/static/chat.js', 'utf8');
// Expose the real client handlers in this throwaway evaluation only; source stays unchanged.
source = source.replace(/  connect\(\);\n\}\)\(\);\s*$/, `
  window.review = {
    setup() {ready=true; selected='A'; restored='A'; conversation={id:'A',title:'Conversation A',model:'synthetic',version:1};
      library=new Map([['A', conversation], ['B',{id:'B',title:'Conversation B',model:'synthetic',version:1}]]);
      socket={readyState:1,send(){}};},
    select,
    missing() {event({v:1,type:'error',id:selecting,code:'gone'});},
    snapshot() {return {selected, restored, libraryIds:[...library.keys()], notice:byId('chat-connection').textContent};}
  };
})();`);
vm.runInNewContext(source, scope);
scope.review.setup();
scope.review.select('B');
scope.review.missing();
const result = scope.review.snapshot();
console.log(JSON.stringify(result));
assert.equal(result.selected, 'A', 'Failed switch to B should preserve visible conversation A');
