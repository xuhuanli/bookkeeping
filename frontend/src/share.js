import { balance, money, statuses } from './utils'

export async function makeOrderImage(order) {
  await document.fonts.ready
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d'),width=900,pad=60
  function lines(text,maxWidth,font='28px sans-serif'){ctx.font=font;const result=[];for(const paragraph of String(text).split('\n')){let line='';for(const char of paragraph){if(ctx.measureText(line+char).width>maxWidth&&line){result.push(line);line=''}line+=char}result.push(line)}return result}
  const customer=lines(order.customer,width-pad*2,'38px sans-serif'),style=lines(order.style,width-pad*2),note=order.note?lines(order.note,width-pad*2,'25px sans-serif'):[]
  const photoRows=Math.ceil(order.photos.length/2),extra=order.tracking?80:0
  canvas.width=width;canvas.height=640+customer.length*52+style.length*42+note.length*38+photoRows*400+extra
  ctx.fillStyle='#f8faf4';ctx.fillRect(0,0,width,canvas.height)
  let y=80
  const text=(value,size=28,color='#52694c',weight='normal')=>{ctx.fillStyle=color;ctx.font=`${weight} ${size}px sans-serif`;ctx.fillText(value,pad,y);y+=size+18}
  text('针线小账  /  手作订单确认',27,'#7d916f');y+=30
  customer.forEach(line=>text(line,38,'#3e573a','bold'))
  text('订单编号：'+order.id,24,'#819276');text('下单日期：'+order.date,24,'#819276');y+=15
  style.forEach(line=>text(line,28));y+=25
  const rows=[['订单报价',order.price],['已收定金',order.deposit],['已收尾款',order.final],['抹零 / 优惠',order.discount]]
  for(const [label,value]of rows){ctx.fillStyle='#6d8062';ctx.font='26px sans-serif';ctx.fillText(label,pad,y);ctx.textAlign='right';ctx.fillText('¥'+money(value),width-pad,y);ctx.textAlign='left';y+=45}
  ctx.fillStyle='#edf0df';ctx.fillRect(pad-16,y-18,width-pad*2+32,90);y+=38
  ctx.fillStyle=balance(order)>0?'#ae844c':'#506a43';ctx.font='bold 32px sans-serif';ctx.fillText(balance(order)>0?'待收尾款':'款项已结清',pad,y);ctx.textAlign='right';ctx.fillText('¥'+money(balance(order)),width-pad,y);ctx.textAlign='left';y+=82
  text('订单状态：'+statuses[order.status],25);if(order.due)text('预计交付：'+order.due,25);if(order.tracking)text('快递单号：'+order.tracking,25)
  if(note.length){y+=12;note.forEach(line=>text(line,25,'#819276'))}
  if(order.photos.length){y+=24;const size=(width-pad*2-20)/2;for(let i=0;i<order.photos.length;i++){const image=new Image();image.src=order.photos[i];await image.decode();const x=pad+(i%2)*(size+20),top=y+Math.floor(i/2)*(size+20);const scale=Math.max(size/image.width,size/image.height);ctx.save();ctx.beginPath();ctx.rect(x,top,size,size);ctx.clip();ctx.drawImage(image,x+(size-image.width*scale)/2,top+(size-image.height*scale)/2,image.width*scale,image.height*scale);ctx.restore()}y+=photoRows*(size+20)}
  y+=35;text('一针一线，认真做；每一份喜欢，好好记。',22,'#96a38c')
  // Trim the preallocated bottom so exported images fit their actual content.
  const output=document.createElement('canvas');output.width=width;output.height=Math.min(canvas.height,y+30);output.getContext('2d').drawImage(canvas,0,0)
  const blob=await new Promise(resolve=>output.toBlob(resolve,'image/png'))
  if(!blob)throw new Error('图片生成失败，可以先复制文字版。')
  return {blob,url:URL.createObjectURL(blob),name:'手作订单-'+order.id+'.png'}
}
