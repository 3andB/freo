/* Read small ID3 text frames locally. The ingest worker remains authoritative. */
(() => {
  const syncsafe = b => (b[0]<<21)|(b[1]<<14)|(b[2]<<7)|b[3];
  window.FreoReadMetadata=async file=>{
    const head=new Uint8Array(await file.slice(0,10).arrayBuffer());
    if(head.length<10||String.fromCharCode(...head.slice(0,3))!=='ID3'||![3,4].includes(head[3])||(head[5]&0xc0))return {};
    const size=Math.min(syncsafe(head.slice(6)),2*1024*1024),bytes=new Uint8Array(await file.slice(10,10+size).arrayBuffer());
    const result={},names={TIT2:'title',TPE1:'artist',TALB:'album',TRCK:'track_number'};
    for(let offset=0;offset+10<=bytes.length;){
      const id=String.fromCharCode(...bytes.slice(offset,offset+4));const chunk=bytes.slice(offset+4,offset+8);const length=head[3]===4?syncsafe(chunk):new DataView(chunk.buffer).getUint32(0);
      if(!length||offset+10+length>bytes.length)break;
      if(names[id]&&!bytes[offset+9]){const payload=bytes.slice(offset+10,offset+10+length),encoding=payload[0],labels=['iso-8859-1','utf-16','utf-16be','utf-8'];if(labels[encoding])result[names[id]]=new TextDecoder(labels[encoding]).decode(payload.slice(1)).replace(/\0/g,'').trim();}
      offset+=10+length;
    }
    return result;
  };
})();
