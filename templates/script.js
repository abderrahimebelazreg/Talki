// Liquid Glass Bottom Navigation – Spring Physics Indicator
document.addEventListener('DOMContentLoaded', () => {
    const nav = document.getElementById('bottomNav');
    const indicator = document.getElementById('indicator');
    const items = Array.from(document.querySelectorAll('.nav-item'));

    let currentLeft = 0;
    let targetLeft = 0;
    let velocity = 0;
    let raf = null;

    const STIFFNESS = 0.2;
    const DAMPING = 0.5;

    function springUpdate() {
        const force = (targetLeft - currentLeft) * STIFFNESS;
        velocity += force;
        velocity *= DAMPING;
        currentLeft += velocity;

        indicator.style.left = `${currentLeft}px`;

        // Continue until settled
        if (Math.abs(targetLeft - currentLeft) > 0.4 || Math.abs(velocity) > 0.4) {
            raf = requestAnimationFrame(springUpdate);
        } else {
            currentLeft = targetLeft;
            indicator.style.left = `${currentLeft}px`;
            velocity = 0;
        }
    }

    function moveIndicator(activeItem) {
        const navRect = nav.getBoundingClientRect();
        const itemRect = activeItem.getBoundingClientRect();

        targetLeft = itemRect.left - navRect.left;
        indicator.style.width = `${itemRect.width}px`;

        // Start spring animation
        if (raf) cancelAnimationFrame(raf);
        velocity = 0; // clean start
        raf = requestAnimationFrame(springUpdate);
    }

    // Tab click handler
    items.forEach(item => {
        item.addEventListener('click', () => {
            if (item.classList.contains('active')) return;

            // Update active state
            items.forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            // Trigger liquid glass movement
            moveIndicator(item);
        });

        // Touch feedback
        item.addEventListener('touchstart', () => {
            if (!item.classList.contains('active')) {
                item.style.transform = 'scale(0.92)';
            }
        });
        item.addEventListener('touchend', () => {
            item.style.transform = '';
        });
    });

    // Initialize indicator on first active tab
    const initialActive = items.find(item => item.classList.contains('active'));
    if (initialActive) {
        const navRect = nav.getBoundingClientRect();
        const itemRect = initialActive.getBoundingClientRect();
        currentLeft = targetLeft = itemRect.left - navRect.left;
        indicator.style.left = `${currentLeft}px`;
        indicator.style.width = `${itemRect.width}px`;
    }

    console.log('%c✅ Premium Liquid Glass Bottom Nav initialized', 'color:#0071e3;font-weight:600');
});