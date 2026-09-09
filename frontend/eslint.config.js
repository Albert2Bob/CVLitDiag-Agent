import js from "@eslint/js";
import vue from "eslint-plugin-vue";
import globals from "globals";
export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...vue.configs["flat/recommended"],
  {
    files: ["**/*.{js,vue}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      // 模板缩进（包括多行表达式）由 Prettier 负责。
      "vue/html-indent": "off",
      "vue/multi-word-component-names": "off",
      "vue/max-attributes-per-line": "off",
      "vue/html-self-closing": "off",
      "vue/singleline-html-element-content-newline": "off",
    },
  },
];
