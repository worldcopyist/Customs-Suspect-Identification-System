// Restricted Markdown: escape first, never accept HTML, images or arbitrary links.
const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function inline(text){
  const tokens=/\\(?<literal>[\\`*_{}\[\]()#+.!|>~-])|`(?<code>[^`]+)`|\*\*(?<strong>[^*]+)\*\*|\*(?<em>[^*]+)\*|!\[(?<image>[^\]]*)\]\((?<imageUrl>[^)]*)\)|\[(?<link>[^\]]+)\]\((?<url>[^)]*)\)/g;
  let out='',cursor=0;
  for(const match of text.matchAll(tokens)){
    out+=escape(text.slice(cursor,match.index));const g=match.groups;
    if(g.literal!==undefined)out+=escape(g.literal);
    else if(g.code!==undefined)out+='<code>'+escape(g.code)+'</code>';
    else if(g.strong!==undefined)out+='<strong>'+escape(g.strong)+'</strong>';
    else if(g.em!==undefined)out+='<em>'+escape(g.em)+'</em>';
    else if(g.image!==undefined)out+=escape(g.image)+'（外部图片已禁用）';
    else out+=escape(g.link)+'（'+escape(g.url)+'）';
    cursor=match.index+match[0].length;
  }
  return out+escape(text.slice(cursor));
}
export function markdown(text){
  const lines=String(text??'').split(/\r?\n/),out=[];let i=0;
  while(i<lines.length){const line=lines[i];
    if(/^```/.test(line)){const code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);i++;out.push('<pre><code>'+escape(code.join('\n'))+'</code></pre>');continue;}
    const heading=/^(#{1,6})\s+(.*)$/.exec(line);if(heading){out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);i++;continue;}
    if(i+1<lines.length&&line.includes('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());const header=cells(line);i+=2;const rows=[];while(i<lines.length&&lines[i].includes('|')&&lines[i].trim())rows.push(cells(lines[i++]));out.push('<div class="table-wrap"><table><thead><tr>'+header.map(x=>'<th>'+inline(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+inline(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>');continue;}
    if(/^\s*([-*+]\s+|\d+\.\s+)/.test(line)){const ordered=/^\s*\d+\./.test(line),items=[];while(i<lines.length&&/^\s*([-*+]\s+|\d+\.\s+)/.test(lines[i]))items.push(lines[i++].replace(/^\s*([-*+]\s+|\d+\.\s+)/,''));const tag=ordered?'ol':'ul';out.push(`<${tag}>`+items.map(x=>'<li>'+inline(x)+'</li>').join('')+`</${tag}>`);continue;}
    if(/^>\s?/.test(line)){out.push('<blockquote>'+inline(line.replace(/^>\s?/,''))+'</blockquote>');i++;continue;}
    if(!line.trim()){i++;continue;}
    out.push('<p>'+inline(line)+'</p>');i++;
  }
  return out.join('');
}
