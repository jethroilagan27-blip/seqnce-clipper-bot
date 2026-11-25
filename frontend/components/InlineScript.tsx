// A script that runs while the page is first parsed (see Next's guide "preventing flash before hydration").
// On the client it is given an inert type, so React doesn't warn about rendering a script tag.
export default function InlineScript({ html }: { html: string }) {
  return <script type={typeof window === "undefined" ? "text/javascript" : "text/plain"} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: html }} />;
}
