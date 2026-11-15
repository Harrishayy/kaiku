/** Semantic unit bounds constrain presentation only; observations and baseline math stay unchanged. */
export function chartDomain(values:readonly number[],unit:string|undefined) {
  const normalized=unit?.replaceAll('–','-').replaceAll(' ','');
  if(normalized==='1-5')return {lo:1,hi:5,padding:0};
  if(normalized==='ratio'||normalized==='0-1')return {lo:0,hi:1,padding:0};
  const finite=values.filter(Number.isFinite);
  let lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;
  if(lo===hi){lo-=1;hi+=1;}
  const padding=(hi-lo)*.08;
  return {lo:lo-padding,hi:hi+padding,padding};
}
