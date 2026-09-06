// Keep server decimal sequence IDs exact; Number loses precision above 2^53.
export function mergeMessages(previous,incoming){
  const bySeq=new Map(previous.map(message=>[String(message.seq),message]));
  for(const message of incoming)bySeq.set(String(message.seq),message);
  return [...bySeq.values()].sort((a,b)=>BigInt(a.seq)<BigInt(b.seq)?-1:BigInt(a.seq)>BigInt(b.seq)?1:0);
}
