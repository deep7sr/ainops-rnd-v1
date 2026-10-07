// A skill step as written in SKILL.md: tool names in `backticks` show as code, indented lines as
// their own lines.

export function StepText({ text }: { text: string }) {
  return (
    <>
      {text.split('\n').map((line, index) => (
        <span key={index} className={index > 0 ? 'block text-muted-foreground' : undefined}>
          {index > 0 && line.startsWith('- ') && '• '}
          {(index > 0 && line.startsWith('- ') ? line.slice(2) : line)
            .split(/(`[^`]+`)/)
            .map((part, i) =>
              part.startsWith('`') && part.endsWith('`') && part.length > 2 ? (
                <code
                  key={i}
                  className="rounded bg-muted px-1 py-px font-mono text-[12px] text-foreground"
                >
                  {part.slice(1, -1)}
                </code>
              ) : (
                part
              ),
            )}
        </span>
      ))}
    </>
  )
}
