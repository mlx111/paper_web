import hljs from "highlight.js/lib/core";
import plaintext from "highlight.js/lib/languages/plaintext";
import python from "highlight.js/lib/languages/python";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import bash from "highlight.js/lib/languages/bash";
import xml from "highlight.js/lib/languages/xml";
import { marked } from "marked";

hljs.registerLanguage("plaintext", plaintext);
hljs.registerLanguage("python", python);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("html", xml);

marked.setOptions({
  breaks: true,
  gfm: true
});

export function renderMarkdown(content) {
  return marked.parse(content || "");
}

export function highlightCodeBlocks(container) {
  if (!container) {
    return;
  }

  container.querySelectorAll("pre code").forEach((block) => {
    if (!block.classList.contains("hljs")) {
      hljs.highlightElement(block);
    }
  });
}
