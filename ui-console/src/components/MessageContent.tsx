// src/components/MessageContent.tsx
import { useState } from "react";

// یک بلاک می‌تونه متن معمولی باشه یا کد
type Block =
  | { type: "text"; content: string }
  | { type: "code"; content: string; language?: string };

interface MessageContentProps {
  text: string;
}

// ساده‌ترین پارسر برای code blocks: ```lang\ncode...``` یا [code lang]\n...\n[/code]
function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = text.split(/\r?\n/);
  let inCode = false;
  let fenceType: "markdown" | "bbcode" | null = null;
  let codeLang: string | undefined;
  let codeBuffer: string[] = [];
  let textBuffer: string[] = [];

  const flushText = () => {
    if (textBuffer.length === 0) return;
    blocks.push({ type: "text", content: textBuffer.join("\n") });
    textBuffer = [];
  };

  const flushCode = () => {
    blocks.push({
      type: "code",
      content: codeBuffer.join("\n").trimEnd(),
      language: codeLang,
    });
    codeBuffer = [];
    codeLang = undefined;
  };

  for (const line of lines) {
    const bbOpen = line.match(/^\[code(?:(?:=|\s+)([A-Za-z0-9_-]+))?\]\s*$/i);
    const bbClose = /^\[\/code\]\s*$/i.test(line);
    const mdOpen = line.match(/^```(\w+)?\s*$/);
    const mdClose = /^```\s*$/.test(line);

    if (!inCode && (bbOpen || mdOpen)) {
      flushText();
      inCode = true;
      if (bbOpen) {
        fenceType = "bbcode";
        codeLang = bbOpen[1];
      } else if (mdOpen) {
        fenceType = "markdown";
        codeLang = mdOpen[1];
      }
      continue;
    }

    if (inCode) {
      if (fenceType === "bbcode" && bbClose) {
        flushCode();
        inCode = false;
        fenceType = null;
        continue;
      }
      if (fenceType === "markdown" && mdClose) {
        flushCode();
        inCode = false;
        fenceType = null;
        continue;
      }
    }

    if (inCode) {
      codeBuffer.push(line);
    } else {
      textBuffer.push(line);
    }
  }

  if (inCode) {
    flushCode();
  } else {
    flushText();
  }

  // اگر هیچ ``` نبود، کل متن یک بلاک text می‌ماند
  if (blocks.length === 0) {
    blocks.push({ type: "text", content: text });
  }

  return blocks;
}

export function MessageContent({ text }: MessageContentProps) {
  const blocks = parseBlocks(text);
  const [copiedBlockIndex, setCopiedBlockIndex] = useState<number | null>(null);

  const handleCopy = async (code: string, index: number) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedBlockIndex(index);
      setTimeout(() => setCopiedBlockIndex(null), 1500);
    } catch {
      // سکوت؛ نیازی به انفجار نیست
    }
  };

function markdownToText(text: string): string {
  return text
    // headings: ### Title -> Title
    .replace(/^#{1,6}\s+/gm, "")

    // images: ![alt](url) -> alt   (must run BEFORE the link regex, which
    // is a subset pattern and would otherwise leave a stray "!")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")

    // links: [Google](https://google.com) -> Google
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")

    // bold / italic
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    // italic underscores: only strip when NOT touching a word character,
    // so snake_case / my_var_name / __init__.py survive untouched
    .replace(/(?<![\w_])_([^_\n]+)_(?![\w_])/g, "$1")

    // strikethrough: ~~text~~ -> text
    .replace(/~~(.*?)~~/g, "$1")

    // inline code: `hello` -> hello
    .replace(/`([^`]+)`/g, "$1")

    // unordered lists: - item / * item -> item
    .replace(/^\s*[-*+]\s+/gm, "")

    // numbered lists: 1. item -> item
    .replace(/^\s*\d+\.\s+/gm, "")

    // blockquote: > text -> text
    .replace(/^\s*>\s?/gm, "")

    // horizontal rules (---, ***, ___, or mixes of 3+)
    .replace(/^\s*([-*_])\1{2,}\s*$/gm, "");
}

  return (
    <div className="space-y-3">
      {blocks.map((block, index) => {
        if (block.type === "text") {
          return (
            <p
              key={index}
              className="whitespace-pre-wrap break-words leading-relaxed"
            >
              {markdownToText(block.content)}
            </p>
          );
        }

        // بلاک کد
        return (
          <div
            key={index}
            className="relative group rounded-xl bg-black/70 border border-white/10 overflow-hidden"
          >
            {/* هدر کد (زبان + دکمه کپی) */}
            <div className="flex items-center justify-between px-3 py-2 text-xs bg-black/60 border-b border-white/10">
              <span className="font-mono text-cyan-300/80">
                {block.language || "code"}
              </span>
              <button
                type="button"
                onClick={() => handleCopy(block.content, index)}
                className="px-2 py-1 rounded-md border border-white/10 text-[10px] uppercase tracking-wider text-gray-300 hover:text-white hover:bg-white/5 transition-colors"
              >
                {copiedBlockIndex === index ? "Copied" : "Copy"}
              </button>
            </div>

            {/* خود کد */}
            <pre className="max-h-[460px] overflow-auto p-3 text-xs md:text-sm bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
              <code className="font-mono text-cyan-100 whitespace-pre">
                {block.content}
              </code>
            </pre>
          </div>
        );
      })}
    </div>
  );
}
