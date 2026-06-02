/**
 * Toast Notification System
 * Displays temporary notifications for user feedback
 */

class ToastManager {
  constructor() {
    this.container = null;
    this.toasts = [];
    this.maxToasts = 5;
    this.init();
  }

  init() {
    // Create toast container
    this.container = document.createElement('div');
    this.container.id = 'toast-container';
    this.container.className = 'toast-container';
    document.body.appendChild(this.container);
  }

  /**
   * Show a toast notification
   * @param {string} message - Message to display
   * @param {string} type - Type: 'success', 'error', 'warning', 'info'
   * @param {number} duration - Duration in ms (0 = manual dismiss)
   */
  show(message, type = 'info', duration = 4000) {
    // Limit number of toasts
    if (this.toasts.length >= this.maxToasts) {
      this.dismiss(this.toasts[0].id);
    }

    const id = `toast-${Date.now()}-${Math.random()}`;
    const toast = this.createToast(id, message, type);
    
    this.container.appendChild(toast);
    this.toasts.push({ id, element: toast });

    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 10);

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(() => this.dismiss(id), duration);
    }

    return id;
  }

  createToast(id, message, type) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.dataset.toastId = id;

    const icons = {
      success: `<svg class="toast-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`,
      error: `<svg class="toast-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>`,
      warning: `<svg class="toast-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>`,
      info: `<svg class="toast-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`
    };

    toast.innerHTML = `
      ${icons[type] || icons.info}
      <div class="toast-message">${this.escapeHtml(message)}</div>
      <button class="toast-close" aria-label="Close">
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    `;

    // Close button handler
    toast.querySelector('.toast-close').addEventListener('click', () => {
      this.dismiss(id);
    });

    return toast;
  }

  dismiss(id) {
    const index = this.toasts.findIndex(t => t.id === id);
    if (index === -1) return;

    const { element } = this.toasts[index];
    element.classList.remove('show');
    element.classList.add('hide');

    setTimeout(() => {
      element.remove();
      this.toasts.splice(index, 1);
    }, 300);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  success(message, duration) {
    return this.show(message, 'success', duration);
  }

  error(message, duration) {
    return this.show(message, 'error', duration);
  }

  warning(message, duration) {
    return this.show(message, 'warning', duration);
  }

  info(message, duration) {
    return this.show(message, 'info', duration);
  }
}

/**
 * Modal Manager
 * Handles modal dialogs with backdrop and accessibility
 */
class ModalManager {
  constructor() {
    this.activeModal = null;
    this.init();
  }

  init() {
    // Close modal on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.activeModal) {
        this.close();
      }
    });
  }

  /**
   * Show a confirmation modal
   * @param {Object} options - Modal options
   * @returns {Promise<boolean>} - Resolves to true if confirmed, false if cancelled
   */
  confirm(options = {}) {
    const {
      title = 'Confirm',
      message = 'Are you sure?',
      confirmText = 'Confirm',
      cancelText = 'Cancel',
      danger = false
    } = options;

    return new Promise((resolve) => {
      const modal = this.createModal(title, message, [
        {
          text: cancelText,
          class: 'btn btn-secondary',
          onClick: () => {
            this.close();
            resolve(false);
          }
        },
        {
          text: confirmText,
          class: `btn ${danger ? 'btn-danger' : 'btn-primary'}`,
          onClick: () => {
            this.close();
            resolve(true);
          }
        }
      ]);

      this.show(modal);
    });
  }

  /**
   * Show an alert modal
   * @param {string} title - Modal title
   * @param {string} message - Modal message
   */
  alert(title, message) {
    return new Promise((resolve) => {
      const modal = this.createModal(title, message, [
        {
          text: 'OK',
          class: 'btn btn-primary',
          onClick: () => {
            this.close();
            resolve(true);
          }
        }
      ]);

      this.show(modal);
    });
  }

  createModal(title, message, buttons) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal-backdrop"></div>
      <div class="modal-dialog" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${this.escapeHtml(title)}</h3>
        </div>
        <div class="modal-body">
          <p>${this.escapeHtml(message)}</p>
        </div>
        <div class="modal-footer">
          ${buttons.map((btn, i) => 
            `<button class="${btn.class}" data-btn-index="${i}">${this.escapeHtml(btn.text)}</button>`
          ).join('')}
        </div>
      </div>
    `;

    // Button handlers
    buttons.forEach((btn, i) => {
      const btnElement = modal.querySelector(`[data-btn-index="${i}"]`);
      btnElement.addEventListener('click', btn.onClick);
    });

    // Close on backdrop click
    modal.querySelector('.modal-backdrop').addEventListener('click', () => {
      if (buttons.length > 1) {
        buttons[0].onClick(); // Trigger cancel
      }
    });

    return modal;
  }

  show(modal) {
    this.activeModal = modal;
    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';

    // Focus first button
    setTimeout(() => {
      const firstBtn = modal.querySelector('button');
      if (firstBtn) firstBtn.focus();
    }, 100);
  }

  close() {
    if (this.activeModal) {
      this.activeModal.classList.add('modal-closing');
      setTimeout(() => {
        this.activeModal.remove();
        this.activeModal = null;
        document.body.style.overflow = '';
      }, 200);
    }
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

/**
 * Loading State Manager
 * Shows loading indicators for async operations
 */
class LoadingManager {
  /**
   * Show loading state on a button
   * @param {HTMLButtonElement} button - Button element
   * @param {string} loadingText - Text to show while loading
   */
  static buttonLoading(button, loadingText = 'Loading...') {
    if (button.dataset.originalText) return; // Already loading

    button.dataset.originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `
      <span class="spinner"></span>
      <span>${loadingText}</span>
    `;
  }

  /**
   * Reset button loading state
   * @param {HTMLButtonElement} button - Button element
   */
  static buttonReset(button) {
    if (!button.dataset.originalText) return;

    button.innerHTML = button.dataset.originalText;
    delete button.dataset.originalText;
    button.disabled = false;
  }

  /**
   * Create a skeleton loader for content
   * @param {number} lines - Number of skeleton lines
   * @returns {string} HTML for skeleton loader
   */
  static skeleton(lines = 3) {
    let html = '<div class="skeleton-container">';
    for (let i = 0; i < lines; i++) {
      const width = Math.random() * 30 + 70; // 70-100%
      html += `<div class="skeleton" style="width: ${width}%; height: 1rem; margin-bottom: 0.5rem;"></div>`;
    }
    html += '</div>';
    return html;
  }
}

// Global instances
const toast = new ToastManager();
const modal = new ModalManager();

// Export for use in other scripts
window.toast = toast;
window.modal = modal;
window.LoadingManager = LoadingManager;

// Example usage:
// toast.success('Post created successfully!');
// toast.error('Failed to delete post');
// await modal.confirm({ title: 'Delete Post', message: 'Are you sure?', danger: true });
// LoadingManager.buttonLoading(button, 'Saving...');
