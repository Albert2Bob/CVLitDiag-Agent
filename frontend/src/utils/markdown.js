import MarkdownIt from "markdown-it";
// Raw HTML is disabled; markdown-it also rejects javascript:/vbscript:/unsafe data URLs.
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
// Uploaded / generated remote images should not initiate unsolicited tracking requests.
md.disable("image");
md.renderer.rules.table_open = () => '<div class="table-scroll"><table>';
md.renderer.rules.table_close = () => "</table></div>";
export const renderMarkdown = (text) =>
  md.render(typeof text === "string" ? text : "");
