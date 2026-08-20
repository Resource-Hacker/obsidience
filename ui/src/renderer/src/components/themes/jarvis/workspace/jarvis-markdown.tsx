// Themed markdown for the JARVIS panes (owner 2026-08-04: "make sure the
// reader can show beautified text and markdown properly"). One shared
// renderer so vault articles and job documents read identically: HUD
// palette, monospace code, GFM tables. react-markdown is pure React (no
// dangerouslySetInnerHTML, CSP-safe); links open nowhere by default — the
// reader is a display surface, not a browser.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function JarvisMarkdown(props: { content: string }) {
  return (
    <div className="jarvis-markdown text-xs leading-5 text-cyan-50/85">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-3 border-b border-cyan-300/15 pb-1 font-mono text-sm font-semibold text-cyan-50 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-1.5 mt-3 font-mono text-[13px] font-semibold text-cyan-100 first:mt-0">
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
            <p className="mb-2 break-words last:mb-0">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="mb-2 list-disc space-y-0.5 pl-5 marker:text-cyan-300/50">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 list-decimal space-y-0.5 pl-5 marker:text-cyan-300/50">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="break-words">{children}</li>,
          a: ({ children }) => (
            // Display-only: remote navigation never leaves a reader pane.
            <span className="text-cyan-300 underline decoration-cyan-300/40">
              {children}
            </span>
          ),
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
        {props.content}
      </ReactMarkdown>
    </div>
  );
}
