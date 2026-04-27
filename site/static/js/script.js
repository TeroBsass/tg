const supportDot = document.querySelector('.support-dot');
const supportForm = document.querySelector('.support-form');
const form = document.getElementById('supportForm');
const el1 = document.getElementById('start_btn');
const formMessage = document.createElement('div');
formMessage.className = 'form-message';
supportForm.appendChild(formMessage);

// Показываем/скрываем форму при клике на точку
supportDot.addEventListener('click', () => {
  supportForm.style.display = supportForm.style.display === 'flex' ? 'none' : 'flex';
});

// Скрыть форму при клике вне её и точки
document.addEventListener('click', (event) => {
  if (!supportForm.contains(event.target) && !supportDot.contains(event.target)) {
    supportForm.style.display = 'none';
    formMessage.textContent = '';
    form.querySelectorAll('.error-message').forEach(el => el.textContent = '');
    form.reset();
  }
});

// Обработка отправки формы с валидацией
form.addEventListener('submit', function(event) {
  event.preventDefault();

  // Очистить ошибки и сообщение
  form.querySelectorAll('.error-message').forEach(el => el.textContent = '');
  formMessage.textContent = '';
  formMessage.style.color = '';

  let hasError = false;
  const email = this.email.value.trim();
  const message = this.message.value.trim();

  if (email === '') {
    this.email.nextElementSibling.textContent = 'Введите email';
    hasError = true;
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    this.email.nextElementSibling.textContent = 'Введите корректный email';
    hasError = true;
  }
  if (message === '') {
    this.message.nextElementSibling.textContent = 'Введите сообщение';
    hasError = true;
  }
  if (hasError) return;

  formMessage.style.color = '#28a745';
  formMessage.textContent = 'Спасибо за ваше сообщение! Мы свяжемся с вами в ближайшее время.';
  const data = { "email":email, "message":message};

  fetch('/api/data', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  })
  .then(response => response.json())
  .then(result => {
    console.log('Success:', result);
  })
  .catch(error => {
    console.error('Error:', error);
  });
  this.reset();

});
el1.addEventListener('click', function(){
    window.location.href = "https://t.me/lhenglish_bot";

});
