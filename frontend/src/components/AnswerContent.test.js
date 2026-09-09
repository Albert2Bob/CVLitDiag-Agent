import { expect, it } from "vitest";
import { createSSRApp } from "vue";
import { renderToString } from "vue/server-renderer";
import AnswerContent from "./AnswerContent.vue";
it("renders real Markdown text without structured answer fields or executable HTML", async () => {
  const html = await renderToString(
    createSSRApp(AnswerContent, {
      run: {
        status: "completed",
        answer: "**Real answer** <script>alert(1)</script>",
        evidence: [],
        draft: "",
        error: null,
      },
    }),
  );
  expect(html).toContain("<strong>Real answer</strong>");
  expect(html).not.toContain("<script>");
});

it.each([
  ["completed", "最终回答"],
  ["running", "回答生成中"],
])("labels %s answers distinctly", async (status, label) => {
  const html = await renderToString(
    createSSRApp(AnswerContent, {
      run: {
        status,
        answer: status === "completed" ? "Done" : null,
        draft: "",
        evidence: [],
      },
    }),
  );
  expect(html).toContain(label);
});
