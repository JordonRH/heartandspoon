import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const css = readFileSync(new URL('../mealie/hearth/web/style.css',import.meta.url),'utf8');
function luminance(hex) {
  let digits = hex.slice(1);
  if (digits.length === 3) digits = [...digits].map(c => c+c).join('');
  const values = [0,2,4].map(i => parseInt(digits.slice(i,i+2),16)/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4);
  return values[0]*.2126 + values[1]*.7152 + values[2]*.0722;
}
function ratio(a,b) { const values = [luminance(a),luminance(b)].sort((x,y) => y-x); return (values[0]+.05)/(values[1]+.05); }
let defaults, count = 0;
for (const match of css.matchAll(/(:root|\[data-theme=[a-z]+\])\{([^}]+)\}/g)) {
  const palette = {...defaults,...Object.fromEntries([...match[2].matchAll(/--([\w-]+):(#[a-f0-9]+)/g)].map(m => [m[1],m[2]]))};
  defaults ||= palette;
  for (const [foreground,background] of [['ink','surface'],['muted','side'],['muted','bg'],['accent','tint'],['accent','hero'],['accent','surface'],['accent-ink','accent'],['error','bg']]) {
    const value = ratio(palette[foreground],palette[background]);
    assert.ok(value >= 4.5, `${match[1]} ${foreground}/${background}: ${value.toFixed(2)} below WCAG AA 4.5`);
  }
  count++;
}
assert.equal(count,5,'Every theme must be checked');
console.log('Five theme palettes pass the checked WCAG AA text/background ratios.');
