let cart=JSON.parse(sessionStorage.getItem('alqatera_cart')||'[]');
function save(){sessionStorage.setItem('alqatera_cart',JSON.stringify(cart));renderCart()}
function addToCart(id,name,price){let p=cart.find(x=>x.id===id);if(p)p.qty++;else cart.push({id,name,price,qty:1});save();document.getElementById('cart').classList.add('open')}
function toggleCart(){document.getElementById('cart').classList.toggle('open');renderCart()}
function renderCart(){let box=document.getElementById('cartitems');if(!box)return;document.getElementById('cartcount').textContent=cart.reduce((a,x)=>a+x.qty,0);box.innerHTML=cart.map(x=>`<div class="cartitem"><span>${esc(x.name)} × ${x.qty}</span><b>${(x.price*x.qty).toFixed(2)} ₼</b></div>`).join('')||'<p class="hint">Səbət hələ boşdur.</p>';document.getElementById('total').textContent=cart.reduce((a,x)=>a+x.price*x.qty,0).toFixed(2)+' ₼'}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function checkout(e){e.preventDefault();if(!cart.length){alert('Səbət boşdur.');return}let r=await fetch('/order',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':window.CSRF},body:JSON.stringify({name:buyer.value,phone:phone.value,address:address.value,items:cart})});let d=await r.json();if(d.ok){alert('Sifarişiniz qəbul edildi. Sifariş №'+d.order_id);cart=[];save();e.target.reset();toggleCart()}else alert(d.error||'Xəta baş verdi.')}
function filterProducts(){let q=document.getElementById('search').value.toLowerCase();document.querySelectorAll('.product').forEach(p=>p.style.display=p.dataset.name.includes(q)?'':'none')}
renderCart();
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});

async function enableOwnerPush(){
  const status=document.getElementById('pushStatus');
  const btn=document.getElementById('enablePush');
  if(!status||!btn)return;
  if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){
    status.textContent='Bu brauzer push bildirişlərini dəstəkləmir.';return;
  }
  try{
    const keyResponse=await fetch('/api/push-key');
    const keyData=await keyResponse.json();
    if(!keyData.publicKey){status.textContent='Bildirişlər üçün hostinqdə VAPID açarları qurulmalıdır.';return;}
    const permission=await Notification.requestPermission();
    if(permission!=='granted'){status.textContent='Bildiriş icazəsi verilmədi.';return;}
    const registration=await navigator.serviceWorker.ready;
    const applicationServerKey=Uint8Array.from(atob(keyData.publicKey.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
    const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey});
    const saved=await fetch('/api/push-subscription',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':window.CSRF},body:JSON.stringify({subscription})});
    if(!saved.ok)throw new Error('Yadda saxlamaq mümkün olmadı');
    status.textContent='Bu cihazda yeni sifariş bildirişləri aktivdir.';
  }catch(err){status.textContent='Bildirişləri aktiv etmək alınmadı. HTTPS və VAPID sazlamalarını yoxla.';}
}
document.getElementById('enablePush')?.addEventListener('click',enableOwnerPush);
