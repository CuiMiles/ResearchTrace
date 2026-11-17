import { mkdir, copyFile, readdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { gzipSync, constants as zlib } from 'node:zlib';
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
// Precompressed siblings: the API serves name.ext.gz to browsers that accept gzip.
const compressible=/\.(js|mjs|css|svg|json|map|wasm|txt|bcmap)$/i;
let written=0;
for(const file of files.filter(file=>compressible.test(file))){
 const source=path.join(staging,file);
 const raw=await readFile(source);
 if(raw.length<1024)continue;
 const packed=gzipSync(raw,{level:zlib.Z_BEST_COMPRESSION});
 if(packed.length>=raw.length*0.9)continue;
 await writeFile(source+'.gz',packed);
 files.push(file+'.gz');
 written+=1;
}
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
console.log(`Published ${files.length} build files (${written} gzip siblings); index replaced last, existing hashed assets retained.`);
