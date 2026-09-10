import ReactMarkdown from "react-markdown";
import CodeBlock from "./CodeBlock";

export default function MarkdownRenderer({ content }) {
  return (
    <ReactMarkdown
      components={{
        pre({ node: _node, children }) {
          return <>{children}</>;
        },
        code({ node: _node, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className ?? "");
          const code = String(children).replace(/\n$/, "");

          if (match) {
            return <CodeBlock code={code} language={match[1]} />;
          }

          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
