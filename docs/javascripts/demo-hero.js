// Home page: the live graph demo is the hero. Once it scrolls out of view on a
// wide screen it docks as a small floating graph until it returns or is closed.
(() => {
  const hero = document.querySelector("[data-demo-hero]");
  if (!hero) return;
  const frame = hero.querySelector(".demo-hero-frame");
  const iframe = frame.querySelector("iframe");
  const close = frame.querySelector(".demo-hero-close");
  const wide = window.matchMedia("(min-width: 1000px) and (prefers-reduced-motion: no-preference)");
  let docked = false, dismissed = false;
  const dock = (next) => {
    if (next === docked) return;
    docked = next;
    frame.classList.toggle("docked", docked);
    close.hidden = !docked;
    iframe.contentWindow?.postMessage({ type: "obsidience-demo-docked", docked }, location.origin);
  };
  new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting) dock(false);
    else if (!dismissed && wide.matches && entry.boundingClientRect.bottom < 0) dock(true);
  }).observe(hero);
  close.addEventListener("click", () => { dismissed = true; dock(false); });
})();
