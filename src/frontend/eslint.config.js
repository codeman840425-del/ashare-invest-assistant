import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  // prototype/ 是独立的 T-F00 原型包，保持不动、不参与正式包的检查
  { ignores: ['prototype/**', 'dist/**', 'dist-mock/**', 'node_modules/**', 'coverage/**'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'no-irregular-whitespace': ['error', { skipJSXText: true, skipStrings: true, skipTemplates: true, skipComments: true }],
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'no-restricted-imports': ['error', {
        patterns: [{ group: ['ag-grid-enterprise', '@ag-grid-enterprise/*'], message: '禁止 AG Grid Enterprise（plan 2.10，契约 §9）' }],
      }],
    },
  },
  {
    files: ['scripts/**/*.mjs', 'eslint.config.js'],
    extends: [js.configs.recommended],
    languageOptions: { ecmaVersion: 2023, globals: globals.node },
  },
  {
    // Playwright 的 page.evaluate 回调在浏览器里执行
    files: ['scripts/screenshot.mjs', 'scripts/screenshot-tf02.mjs'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
);
