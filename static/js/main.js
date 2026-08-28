// Auto hide flash messages
document.addEventListener('DOMContentLoaded', function () {
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach((flash, index) => {
        setTimeout(() => {
            flash.style.transition = 'opacity 0.4s, transform 0.4s';
            flash.style.opacity = '0';
            flash.style.transform = 'translateX(20px)';
            setTimeout(() => flash.remove(), 400);
        }, 4000 + index * 300);
    });

    // Inject CSRF token into all forms (حماية من هجمات CSRF)
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
        const token = csrfMeta.getAttribute('content');
        document.querySelectorAll('form').forEach(form => {
            if (!form.querySelector('input[name="_csrf_token"]')) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = '_csrf_token';
                input.value = token;
                form.appendChild(input);
            }
        });
    }

    // Sidebar toggle for mobile
    const toggleBtn = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (toggleBtn && sidebar) {
        // Create backdrop for mobile
        let backdrop = document.createElement('div');
        backdrop.className = 'sidebar-overlay';
        document.body.appendChild(backdrop);

        const closeSidebar = () => {
            sidebar.classList.remove('open');
            backdrop.classList.remove('show');
            document.body.classList.remove('no-scroll');
        };

        toggleBtn.addEventListener('click', () => {
            const isOpen = sidebar.classList.toggle('open');
            backdrop.classList.toggle('show', isOpen);
            if (isOpen) document.body.classList.add('no-scroll');
        });

        backdrop.addEventListener('click', closeSidebar);
        sidebar.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', closeSidebar));
    }
});

// Dark mode toggle
(function () {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const icon = btn.querySelector('i');
    const root = document.documentElement;
    function sync() {
        const dark = root.getAttribute('data-theme') === 'dark';
        icon.className = dark ? 'fas fa-sun' : 'fas fa-moon';
        btn.classList.toggle('theme-toggle-active', dark);
    }
    btn.addEventListener('click', function () {
        const dark = root.getAttribute('data-theme') === 'dark';
        if (dark) {
            root.removeAttribute('data-theme');
            localStorage.setItem('hr-theme', 'light');
        } else {
            root.setAttribute('data-theme', 'dark');
            localStorage.setItem('hr-theme', 'dark');
        }
        sync();
    });
    sync();
})();

// Modal helpers
function openModal(id) {
    document.getElementById(id).classList.add('show');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('show');
}

document.addEventListener('click', function (e) {
    if (e.target.classList && e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('show');
    }
});

document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.show').forEach(m => m.classList.remove('show'));
    }
});

// Confirm dialog helper
function confirmAction(message, formId) {
    if (confirm(message)) {
        document.getElementById(formId).submit();
    }
    return false;
}

// Print current page (for payslips and reports)
function printPage() {
    window.print();
}

// Auto-select value on number inputs
document.addEventListener('focusin', function (e) {
    if (e.target.type === 'number') {
        e.target.select();
    }
});

// Live clock for the topbar
function updateClock() {
    const el = document.getElementById('live-clock');
    if (!el) return;
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    el.textContent = `${hours}:${minutes}:${seconds}`;
}
setInterval(updateClock, 1000);

// Client-side toast helper (for copy actions etc.)
function flash(message, category) {
    const container = document.getElementById('flash-container');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'flash ' + (category || 'success');
    const icon = category === 'danger' ? '<i class="fas fa-exclamation-circle"></i>'
        : category === 'warning' ? '<i class="fas fa-exclamation-triangle"></i>'
        : '<i class="fas fa-check-circle"></i>';
    div.innerHTML = icon + ' ' + message;
    container.appendChild(div);
    setTimeout(() => {
        div.style.transition = 'opacity 0.4s, transform 0.4s';
        div.style.opacity = '0';
        div.style.transform = 'translateX(20px)';
        setTimeout(() => div.remove(), 400);
    }, 2500);
}