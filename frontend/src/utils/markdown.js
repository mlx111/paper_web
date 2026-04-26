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

const IMAGE_PLACEHOLDER_RE = /<<IMAGE:[0-9a-fA-F]{8}>>/g;

function escapeMarkdownUrl(value) {
  return String(value || "").replace(/[)\s]/g, (match) => encodeURIComponent(match));
}

export function replaceImagePlaceholders(content, imageMap = {}) {
  let result = String(content || "");
  const validMap = imageMap && typeof imageMap === "object" ? imageMap : {};
  result = result.replace(IMAGE_PLACEHOLDER_RE, (placeholder) => {
    const url = validMap[placeholder];
    if (!url) {
      return "";
    }
    return `\n![文档图片](${escapeMarkdownUrl(url)})\n`;
  });
  return result;
}

export function renderMarkdown(content, imageMap = {}) {
  return marked.parse(replaceImagePlaceholders(content || "", imageMap));
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
