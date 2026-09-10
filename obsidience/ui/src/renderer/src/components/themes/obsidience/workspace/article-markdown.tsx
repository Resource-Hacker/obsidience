// Themed markdown for the Executive panes (owner 2026-08-04: "make sure the
// reader can show beautified text and markdown properly"). One shared
// renderer so vault articles and Task documents read identically: HUD
// palette, monospace code, GFM tables. react-markdown is pure React (no
// dangerouslySetInnerHTML, CSP-safe); links open nowhere by default — the
// reader is a display surface, not a browser.
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

const READER_REF_PREFIX = "#obsidience-ref=";
const SOURCE_CITATION = /^source:\/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function readableWikiLinks(content: string): string {
  return content.replace(/\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/g, (_match, rawRef, rawLabel) => {
    const ref = String(rawRef).trim();
    const label = String(rawLabel || ref.split("/").pop() || ref)
      .trim().replaceAll("[", "\\[").replaceAll("]", "\\]");
    return `[${label}](${READER_REF_PREFIX}${encodeURIComponent(ref)})`;
  });
}

export function ArticleMarkdown(props: {
  content: string;
  variant?: "default" | "reader" | "index";
  onNavigate?: (ref: string) => void;
  onSourceNavigate?: (citation: string) => void;
}) {
  const variant = props.variant ?? "default";
  const comfortable = variant !== "default";
  const content = props.onNavigate ? readableWikiLinks(props.content) : props.content;
  return (
    <div className={`obsidience-markdown ${comfortable
      ? "font-mono text-[13px] leading-6 text-cyan-50/82"
      : "text-xs leading-5 text-cyan-50/85"}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => SOURCE_CITATION.test(url) ? url : defaultUrlTransform(url)}
        components={{
          h1: ({ children }) => (
            <h1 className={`${comfortable
              ? "mb-4 mt-7 border-b border-cyan-300/15 pb-2 text-[17px] font-semibold tracking-[0.03em] text-cyan-50"
              : "mb-2 mt-3 border-b border-cyan-300/15 pb-1 text-sm font-semibold text-cyan-50"} first:mt-0`}>
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className={`${comfortable
              ? "mb-3 mt-7 border-b border-cyan-300/12 pb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300/70"
              : "mb-1.5 mt-3 text-[13px] font-semibold text-cyan-100"} first:mt-0`}>
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-2.5 font-mono text-xs font-semibold uppercase tracking-wider text-cyan-200/80 first:mt-0">
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4 className="mb-1 mt-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-cyan-300/60">
              {children}
            </h4>
          ),
          p: ({ children }) => (
            <p className={`${comfortable ? "mb-4" : "mb-2"} break-words last:mb-0`}>{children}</p>
          ),
          ul: ({ children }) => (
            <ul className={variant === "index"
              ? "mb-5 space-y-2.5"
              : "mb-2 list-disc space-y-0.5 pl-5 marker:text-cyan-300/50"}>
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 list-decimal space-y-0.5 pl-5 marker:text-cyan-300/50">
              {children}
            </ol>
          ),
          li: ({ children }) => variant === "index" ? (
            <li className="break-words rounded-md border border-cyan-300/10 bg-[#020a12]/70 px-3 py-2.5 text-cyan-100/68 shadow-[inset_2px_0_rgba(34,211,238,0.12)]">
              {children}
            </li>
          ) : <li className="break-words">{children}</li>,
          a: ({ children, href }) => {
            if (href && SOURCE_CITATION.test(href) && props.onSourceNavigate) {
              return (
                <button type="button" onClick={() => props.onSourceNavigate?.(href)}
                  className="mr-1 inline text-left font-semibold text-cyan-200 underline decoration-cyan-300/30 underline-offset-2 hover:text-cyan-50 hover:decoration-cyan-200/70">
                  {children}
                </button>
              );
            }
            if (href?.startsWith(READER_REF_PREFIX) && props.onNavigate) {
              const ref = decodeURIComponent(href.slice(READER_REF_PREFIX.length));
              return (
                <button type="button" onClick={() => props.onNavigate?.(ref)}
                  className="mr-1 inline text-left font-semibold text-cyan-200 underline decoration-cyan-300/30 underline-offset-2 hover:text-cyan-50 hover:decoration-cyan-200/70">
                  {children}
                </button>
              );
            }
            // Display-only: remote navigation never leaves a reader pane.
            return <span className="text-cyan-300 underline decoration-cyan-300/40">{children}</span>;
          },
          strong: ({ children }) => (
            <strong className="font-semibold text-cyan-50">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          blockquote: ({ children }) => (
            <blockquote className="mb-2 border-l-2 border-cyan-300/30 pl-3 text-cyan-100/70">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-3 border-cyan-300/15" />,
          code: ({ children, className }) =>
            className ? (
              // Block code (language-* className from the fence).
              <code className="block font-mono text-[10px] leading-4 text-cyan-100/90">
                {children}
              </code>
            ) : (
              <code className="rounded bg-cyan-300/10 px-1 py-px font-mono text-[10px] text-cyan-100">
                {children}
              </code>
            ),
          pre: ({ children }) => (
            <pre className="mb-2 overflow-x-auto whitespace-pre-wrap break-words rounded border border-cyan-300/15 bg-slate-950/70 p-2">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <table className="mb-2 w-full border-collapse font-mono text-[10px]">
              {children}
            </table>
          ),
          thead: ({ children }) => (
            <thead className="text-left uppercase tracking-wider text-cyan-300/50">
              {children}
            </thead>
          ),
          th: ({ children }) => (
            <th className="border-b border-cyan-300/20 px-2 py-1 font-normal">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-cyan-300/10 px-2 py-1 align-top text-cyan-50/85">
              {children}
            </td>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
