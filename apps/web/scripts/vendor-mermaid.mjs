import { mkdir, copyFile, readdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=path.join(root,'node_modules/mermaid/dist');
const destination=path.join(root,'public/vendor/mermaid');
await rm(destination,{recursive:true,force:true});
await mkdir(destination,{recursive:true});
// The official pinned prebuilt modules remain local. Avoid rebundling every
// diagram renderer during a lite deployment build, and omit source maps/tests.
await copyFile(path.join(source,'mermaid.esm.min.mjs'),path.join(destination,'mermaid.esm.min.mjs'));
const chunks=path.join(source,'chunks/mermaid.esm.min');
await mkdir(path.join(destination,'chunks/mermaid.esm.min'),{recursive:true});
for(const file of await readdir(chunks)){if(file.endsWith('.mjs'))await copyFile(path.join(chunks,file),path.join(destination,'chunks/mermaid.esm.min',file))}
console.log('Prepared pinned local Mermaid modules.');
