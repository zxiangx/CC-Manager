import { decodeString } from 'micromark-util-decode-string';

interface MarkdownPosition {
  start?: { offset?: number };
  end?: { offset?: number };
}

interface MarkdownNode {
  type: string;
  value?: string;
  children?: MarkdownNode[];
  position?: MarkdownPosition;
  data?: Record<string, unknown>;
}

interface MarkdownFile {
  value?: unknown;
}

const SKIP_DESCENDANTS = new Set([
  'code',
  'definition',
  'html',
  'image',
  'imageReference',
  'inlineCode',
  'link',
  'linkReference',
  'math',
  'inlineMath',
]);

function isMarkdownNode(value: unknown): value is MarkdownNode {
  return Boolean(
    value
    && typeof value === 'object'
    && typeof (value as { type?: unknown }).type === 'string',
  );
}

function sourceForNode(node: MarkdownNode, source: string): string | null {
  const start = node.position?.start?.offset;
  const end = node.position?.end?.offset;
  if (
    typeof start !== 'number'
    || typeof end !== 'number'
    || start < 0
    || end < start
    || end > source.length
  ) {
    return null;
  }
  return source.slice(start, end);
}

function isEscaped(source: string, index: number): boolean {
  let precedingBackslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === '\\'; cursor -= 1) {
    precedingBackslashes += 1;
  }
  return precedingBackslashes % 2 === 1;
}

function findDelimiter(
  source: string,
  closingCharacter: '(' | ')' | '[' | ']',
  fromIndex: number,
): number {
  for (let index = fromIndex; index < source.length - 1; index += 1) {
    if (
      source[index] === '\\'
      && source[index + 1] === closingCharacter
      && !isEscaped(source, index)
    ) {
      return index;
    }
  }
  return -1;
}

function inlineMathNode(value: string): MarkdownNode {
  return {
    type: 'inlineMath',
    value,
    data: {
      hName: 'code',
      hProperties: { className: ['language-math', 'math-inline'] },
      hChildren: [{ type: 'text', value }],
    },
  };
}

function displayMathNode(value: string): MarkdownNode {
  return {
    type: 'math',
    value,
    data: {
      hName: 'pre',
      hChildren: [{
        type: 'element',
        tagName: 'code',
        properties: { className: ['language-math', 'math-display'] },
        children: [{ type: 'text', value }],
      }],
    },
  };
}

function stripOneLineEnding(value: string, fromStart: boolean): string {
  if (fromStart) return value.replace(/^(?:\r\n|\r|\n)/, '');
  return value.replace(/(?:\r\n|\r|\n)$/, '');
}

function trailingDisplayPunctuation(raw: string): string | null {
  const match = /^[ \t]*([,.;:!?])?[ \t]*$/.exec(raw);
  return match ? match[1] || '' : null;
}

function parseDisplayMathSource(raw: string): MarkdownNode | null {
  const leadingWhitespace = raw.match(/^[ \t]*/)?.[0].length || 0;
  const opening = findDelimiter(raw, '[', leadingWhitespace);
  if (opening !== leadingWhitespace) return null;

  const closing = findDelimiter(raw, ']', opening + 2);
  if (closing < 0) return null;
  const punctuation = trailingDisplayPunctuation(raw.slice(closing + 2));
  if (punctuation === null) return null;

  let value = raw.slice(opening + 2, closing);
  value = stripOneLineEnding(value, true);
  value = stripOneLineEnding(value, false);
  return displayMathNode(value + punctuation);
}

function parseDisplayMath(paragraph: MarkdownNode, source: string): MarkdownNode | null {
  const raw = sourceForNode(paragraph, source);
  return raw === null ? null : parseDisplayMathSource(raw);
}

interface HeadingDisplayMathMatch {
  node: MarkdownNode;
  consumed: number;
}

function displayValueWithCloser(
  raw: string,
  opener: '\\[' | '$$',
): string | null {
  if (!raw.startsWith(opener)) return null;

  const closing = opener === '\\['
    ? findDelimiter(raw, ']', opener.length)
    : raw.indexOf('$$', opener.length);
  if (closing < 0) return null;
  const punctuation = trailingDisplayPunctuation(raw.slice(closing + 2));
  if (punctuation === null) return null;
  return raw.slice(opener.length, closing) + punctuation;
}

/**
 * Recover a display formula when a model accidentally emits its opener as an
 * ATX heading (`# \\[` or `### $$`). Markdown has already split that source
 * into a heading plus a paragraph, so the repair must join AST siblings rather
 * than rewrite raw Markdown. A heading containing any prose is left alone.
 */
function parseHeadingPrefixedDisplayMath(
  children: MarkdownNode[],
  index: number,
  source: string,
): HeadingDisplayMathMatch | null {
  const heading = children[index];
  if (heading.type !== 'heading') return null;

  const headingRaw = sourceForNode(heading, source);
  if (headingRaw === null) return null;

  // A standalone `=` inside a multiline formula is parsed by Markdown as a
  // Setext heading underline. Rejoin that heading with the following paragraph
  // and recover the original display formula from their shared source range.
  // This is deliberately gated by a leading `\[` and a complete closing `\]`.
  const continuation = children[index + 1];
  if (headingRaw.trimStart().startsWith('\\[') && continuation?.type === 'paragraph') {
    const start = heading.position?.start?.offset;
    const end = continuation.position?.end?.offset;
    if (typeof start === 'number' && typeof end === 'number') {
      const setextFormula = parseDisplayMathSource(source.slice(start, end));
      if (setextFormula) return { node: setextFormula, consumed: 2 };
    }
  }

  const match = /^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*$/.exec(headingRaw);
  if (!match) return null;
  const body = match[1];
  const opener = body.startsWith('\\[') ? '\\[' : body.startsWith('$$') ? '$$' : null;
  if (!opener) return null;

  const sameLineValue = displayValueWithCloser(body, opener);
  if (sameLineValue !== null) {
    return { node: displayMathNode(sameLineValue), consumed: 1 };
  }
  if (body !== opener) return null;

  if (!continuation || continuation.type !== 'paragraph') return null;
  const continuationRaw = sourceForNode(continuation, source);
  if (continuationRaw === null) return null;
  if (opener === '$$') {
    // remark-math recognizes the orphaned closing `$$` as an empty math node,
    // leaving the formula body in the paragraph between it and the heading.
    const closing = children[index + 2];
    if (
      closing?.type === 'math'
      && closing.value === ''
      && sourceForNode(closing, source)?.trim() === '$$'
    ) {
      return { node: displayMathNode(continuationRaw), consumed: 3 };
    }
  }
  const value = displayValueWithCloser(opener + continuationRaw, opener);
  if (value === null) return null;
  return { node: displayMathNode(value), consumed: 2 };
}

function splitInlineMath(node: MarkdownNode, source: string): MarkdownNode[] | null {
  const raw = sourceForNode(node, source);
  if (raw === null) return null;

  const transformed: MarkdownNode[] = [];
  let cursor = 0;
  let searchFrom = 0;
  let found = false;

  while (searchFrom < raw.length - 1) {
    const opening = findDelimiter(raw, '(', searchFrom);
    if (opening < 0) break;

    const closing = findDelimiter(raw, ')', opening + 2);
    const nextOpening = findDelimiter(raw, '(', opening + 2);
    const lineEnding = raw.slice(opening + 2).search(/[\r\n]/);
    if (
      closing < 0
      || (lineEnding >= 0 && opening + 2 + lineEnding < closing)
    ) {
      searchFrom = opening + 2;
      continue;
    }
    if (nextOpening >= 0 && nextOpening < closing) {
      searchFrom = nextOpening;
      continue;
    }

    if (opening > cursor) {
      transformed.push({ type: 'text', value: decodeString(raw.slice(cursor, opening)) });
    }
    transformed.push(inlineMathNode(raw.slice(opening + 2, closing)));
    cursor = closing + 2;
    searchFrom = cursor;
    found = true;
  }

  if (!found) return null;
  if (cursor < raw.length) {
    transformed.push({ type: 'text', value: decodeString(raw.slice(cursor)) });
  }
  return transformed;
}

function transformChildren(parent: MarkdownNode, source: string): void {
  if (!parent.children || SKIP_DESCENDANTS.has(parent.type)) return;

  const transformed: MarkdownNode[] = [];
  for (let index = 0; index < parent.children.length;) {
    const headingDisplayMath = parseHeadingPrefixedDisplayMath(
      parent.children,
      index,
      source,
    );
    if (headingDisplayMath) {
      transformed.push(headingDisplayMath.node);
      index += headingDisplayMath.consumed;
      continue;
    }

    const child = parent.children[index];
    if (child.type === 'paragraph') {
      const displayMath = parseDisplayMath(child, source);
      if (displayMath) {
        transformed.push(displayMath);
        index += 1;
        continue;
      }
    }

    if (child.type === 'text') {
      transformed.push(...(splitInlineMath(child, source) || [child]));
      index += 1;
      continue;
    }

    transformChildren(child, source);
    transformed.push(child);
    index += 1;
  }
  parent.children = transformed;
}

/**
 * Parse Codex's `\\(...\\)` and `\\[...\\]` notation after Markdown has
 * formed its AST. Source positions recover the escaped delimiters without
 * rewriting URLs, HTML, code, definitions, images, or link destinations.
 * Inline pairs are deliberately confined to one text node, and display math
 * must occupy a whole paragraph, so delimiters cannot capture unrelated AST.
 */
export function remarkBackslashMath() {
  return (tree: unknown, file: MarkdownFile): void => {
    if (!isMarkdownNode(tree) || typeof file.value !== 'string') return;
    transformChildren(tree, file.value);
  };
}
