// ── Support widget ──────────────────────────────────────────────
const supportDot  = document.querySelector('.support-dot');
const supportForm = document.querySelector('.support-form');
const form        = document.getElementById('supportForm');

if (supportDot && supportForm && form) {
  const formMessage = document.createElement('div');
  formMessage.className = 'form-message';
  supportForm.appendChild(formMessage);

  supportDot.addEventListener('click', (e) => {
    e.stopPropagation();
    supportForm.style.display = supportForm.style.display === 'flex' ? 'none' : 'flex';
  });

  document.addEventListener('click', (event) => {
    if (!supportForm.contains(event.target) && !supportDot.contains(event.target)) {
      supportForm.style.display = 'none';
      formMessage.textContent = '';
      form.querySelectorAll('.error-message').forEach(el => clearError(el));
      form.reset();
    }
  });

  form.addEventListener('submit', function(event) {
    event.preventDefault();
    form.querySelectorAll('.error-message').forEach(el => clearError(el));
    formMessage.innerHTML = '';
    let hasError = false;
    const email        = this.email.value.trim();
    const message      = this.message.value.trim();
    const emailError   = this.email.nextElementSibling;
    const messageError = this.message.nextElementSibling;
    if (email === '') { showError(emailError, 'Введите email'); hasError = true; }
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { showError(emailError, 'Введите корректный email'); hasError = true; }
    if (message === '') { showError(messageError, 'Введите сообщение'); hasError = true; }
    if (hasError) return;
    formMessage.innerHTML = `<div class="success-msg"><div class="success-msg__icon">✓</div><div><div class="success-msg__title">Отправлено!</div><div class="success-msg__text">Мы свяжемся с вами в ближайшее время.</div></div></div>`;
    fetch('/api/data', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, message }) })
      .then(r => r.json()).then(r => console.log('Success:', r)).catch(e => console.error('Error:', e));
    this.reset();
  });
}

function showError(span, text) {
  span.textContent = text;
  span.classList.add('visible');
}

function clearError(span) {
  span.textContent = '';
  span.classList.remove('visible');
}

// ── Profile / Auth modal ─────────────────────────────────────────
const profileBtn      = document.getElementById('profileBtn');
const profileDropdown = document.getElementById('profileDropdown');
const authModal       = document.getElementById('authModal');

profileBtn.onclick = (e) => {
  e.stopPropagation();
  if (window.TG_USER) profileDropdown.classList.toggle('open');
  else if (authModal) authModal.classList.add('open');
};

const modalClose = document.getElementById('modalClose');
if (authModal) {
  if (modalClose) modalClose.onclick = () => authModal.classList.remove('open');
  authModal.onclick = (e) => { if (e.target === authModal) authModal.classList.remove('open'); };
}

const logoutBtn = document.getElementById('logoutBtn');
if (logoutBtn) {
  logoutBtn.addEventListener('click', () => {
    window.location.href = '/auth/logout';
  });
}

// ── Burger / Mobile nav ──────────────────────────────────────────
const burgerBtn = document.getElementById('burgerBtn');
const mobileNav = document.getElementById('mobileNav');

burgerBtn.onclick = (e) => {
  e.stopPropagation();
  burgerBtn.classList.toggle('open');
  mobileNav.classList.toggle('open');
};

document.addEventListener('click', (e) => {
  if (!profileBtn.contains(e.target))
    profileDropdown.classList.remove('open');

  if (!burgerBtn.contains(e.target) && !mobileNav.contains(e.target)) {
    mobileNav.classList.remove('open');
    burgerBtn.classList.remove('open');
  }
});

function applyUser(user) {
  if (!user) return;
  const nameEl   = document.getElementById('profileName');
  const dNameEl  = document.getElementById('dropdownName');
  const dUserEl  = document.getElementById('dropdownUsername');
  const avatarEl = document.getElementById('profileAvatar');

  if (nameEl)  nameEl.textContent  = user.first_name;
  if (dNameEl) dNameEl.textContent = user.first_name;
  if (user.username && dUserEl) dUserEl.textContent = '@' + user.username;

  if (avatarEl) {
    if (user.photo_url) avatarEl.innerHTML = `<img src="${user.photo_url}" alt="">`;
    else avatarEl.textContent = user.first_name.charAt(0).toUpperCase();
  }
}
