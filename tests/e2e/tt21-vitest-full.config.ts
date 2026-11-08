import { defineConfig } from 'vitest/config';
import { resolve } from 'node:path';
const root = resolve(__dirname, '../..');
export default defineConfig({test:{projects:[
  {extends:resolve(root,'src/frontend/vite.config.ts'),root:resolve(root,'src/frontend'),test:{name:'application'}},
  {extends:resolve(root,'tests/vitest.config.ts'),root:resolve(root,'tests'),test:{name:'test-suite'}}
]}});
