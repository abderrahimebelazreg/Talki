document.addEventListener("DOMContentLoaded", () => {
    const nav = document.getElementById("bottomNav");
    const indicator = document.getElementById("indicator");
    const items = Array.from(document.querySelectorAll("#bottomNav .nav-item"));

    if (!nav || !indicator || items.length === 0) {
        return;
    }

    const STORAGE_KEY = "bottom-nav-origin-index";
    const STIFFNESS = 0.2;
    const DAMPING = 0.5;

    let currentLeft = 0;
    let targetLeft = 0;
    let velocity = 0;
    let raf = null;

    function getItemLeft(item) {
        const navRect = nav.getBoundingClientRect();
        const itemRect = item.getBoundingClientRect();
        return itemRect.left - navRect.left;
    }

    function setIndicator(item, left) {
        indicator.style.left = `${left}px`;
        indicator.style.width = `${item.getBoundingClientRect().width}px`;
    }

    function springUpdate() {
        const force = (targetLeft - currentLeft) * STIFFNESS;
        velocity += force;
        velocity *= DAMPING;
        currentLeft += velocity;

        indicator.style.left = `${currentLeft}px`;

        if (Math.abs(targetLeft - currentLeft) > 0.4 || Math.abs(velocity) > 0.4) {
            raf = requestAnimationFrame(springUpdate);
            return;
        }

        currentLeft = targetLeft;
        indicator.style.left = `${currentLeft}px`;
        velocity = 0;
        raf = null;
    }

    function moveIndicator(activeItem, animate = true) {
        targetLeft = getItemLeft(activeItem);
        indicator.style.width = `${activeItem.getBoundingClientRect().width}px`;

        if (!animate) {
            if (raf) {
                cancelAnimationFrame(raf);
            }
            currentLeft = targetLeft;
            velocity = 0;
            raf = null;
            indicator.style.left = `${currentLeft}px`;
            return;
        }

        if (raf) {
            cancelAnimationFrame(raf);
        }
        velocity = 0;
        raf = requestAnimationFrame(springUpdate);
    }

    items.forEach((item) => {
        item.addEventListener("click", () => {
            const previousIndex = items.findIndex((navItem) =>
                navItem.classList.contains("active"),
            );

            if (previousIndex >= 0) {
                sessionStorage.setItem(STORAGE_KEY, String(previousIndex));
            }
        });

        item.addEventListener("touchstart", () => {
            if (!item.classList.contains("active")) {
                item.style.transform = "scale(0.92)";
            }
        }, { passive: true });

        item.addEventListener("touchend", () => {
            item.style.transform = "";
        }, { passive: true });

        item.addEventListener("touchcancel", () => {
            item.style.transform = "";
        }, { passive: true });
    });

    const activeItem =
        items.find((item) => item.classList.contains("active")) || items[0];
    const activeIndex = items.indexOf(activeItem);
    const originIndex = Number.parseInt(
        sessionStorage.getItem(STORAGE_KEY) || "",
        10,
    );

    if (
        Number.isInteger(originIndex) &&
        originIndex >= 0 &&
        originIndex < items.length &&
        originIndex !== activeIndex
    ) {
        currentLeft = getItemLeft(items[originIndex]);
        setIndicator(items[originIndex], currentLeft);
        requestAnimationFrame(() => moveIndicator(activeItem));
    } else {
        currentLeft = getItemLeft(activeItem);
        setIndicator(activeItem, currentLeft);
    }

    sessionStorage.removeItem(STORAGE_KEY);

    window.addEventListener("resize", () => {
        moveIndicator(
            items.find((item) => item.classList.contains("active")) || activeItem,
            false,
        );
    });
});
