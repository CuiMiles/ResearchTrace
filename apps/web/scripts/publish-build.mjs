import { mkdir, copyFile, readdir, rename, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const staging=path.join(root,'dist-next');
const destination=path.join(root,'dist');
if(!(await stat(path.join(staging,'index.html'))).isFile())throw new Error('Staged build has no index.html; live build untouched.');
const files=[];
async function collect(directory,prefix=''){
 for(const entry of await readdir(directory,{withFileTypes:true})){
  const relative=path.join(prefix,entry.name);
  if(entry.isDirectory())await collect(path.join(directory,entry.name),relative);
  else if(entry.isFile())files.push(relative);
 }
}
await collect(staging);
const regular=files.filter(file=>file!=='index.html'&&path.basename(file)!=='mermaid.esm.min.mjs');
const vendorEntries=files.filter(file=>path.basename(file)==='mermaid.esm.min.mjs');
async function publish(relative){
 const target=path.join(destination,relative);
 await mkdir(path.dirname(target),{recursive:true});
 const temporary=target+'.next-'+process.pid;
 await copyFile(path.join(staging,relative),temporary);
 await rename(temporary,target);
}
// New hashed assets and vendor chunks land before either entry module references
// them. Old hashed assets remain available to already open browser tabs.
for(const file of [...regular,...vendorEntries])await publish(file);
await publish('index.html');
console.log(`Published ${files.length} build files; index replaced last, existing hashed assets retained.`);
