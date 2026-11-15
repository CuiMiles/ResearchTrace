import { defineConfig } from 'vite';
export default defineConfig({server:{proxy:{'/api':'http://127.0.0.1:18970','/healthz':'http://127.0.0.1:18970'}},build:{target:'es2022'}});
