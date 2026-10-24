"use strict";

// All forms, navigation, filtering and account flows work without JavaScript.
document.querySelectorAll("[data-password]").forEach((button) => {
  const field = document.getElementById(button.dataset.password);
  if (!field) return;
  const label = button.getAttribute("aria-label").replace(/^Show /, "");
  button.addEventListener("click", () => {
    const showing = field.type === "password";
    field.type = showing ? "text" : "password";
    button.setAttribute("aria-pressed", String(showing));
    button.setAttribute("aria-label", `${showing ? "Hide" : "Show"} ${label}`);
  });
});

document.querySelectorAll("[data-dismiss-notice]").forEach((button) => {
  button.addEventListener("click", () => button.closest(".notice").remove());
});

const dialog = document.getElementById("confirm-dialog");
let pending = null;
if (dialog && typeof dialog.showModal === "function") {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "true") {
        delete form.dataset.confirmed;
        return;
      }
      event.preventDefault();
      pending = {
        form,
        submitter: event.submitter
      };
      document.getElementById("confirm-message").textContent = form.dataset.confirm;
      document.getElementById("confirm-title").textContent = form.dataset.confirm.includes("account") ? "Close your account?" : "Let this item go?";
      dialog.showModal();
      document.getElementById("confirm-cancel").focus();
    });
  });
  document.getElementById("confirm-cancel").addEventListener("click", () => dialog.close());
  document.getElementById("confirm-accept").addEventListener("click", () => {
    const action = pending;
    if (!action) return;
    action.form.dataset.confirmed = "true";
    dialog.close();
    action.form.requestSubmit(action.submitter);
  });
  dialog.addEventListener("close", () => {
    if (pending?.submitter) pending.submitter.focus();
    pending = null;
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
}

const sidebar = document.getElementById("sidebar");
const backdrop = document.querySelector(".sidebar-backdrop");
const menu = document.querySelector(".mobile-menu");
const content = document.querySelector(".workspace-content");

function toggleNavigation(force) {
  if (!sidebar || !backdrop || !menu || !content) return;
  const opened = typeof force === "boolean" ? force : !document.body.classList.contains("nav-open");
  document.body.classList.toggle("nav-open", opened);
  backdrop.hidden = !opened;
  menu.setAttribute("aria-expanded", String(opened));
  content.inert = opened;
  if (opened) sidebar.querySelector("a").focus();
  else menu.focus();
}
document.querySelectorAll("[data-toggle-sidebar]").forEach((button) => button.addEventListener("click", () => toggleNavigation()));
document.addEventListener("keydown", (event) => {
  if (!document.body.classList.contains("nav-open")) return;
  if (event.key === "Escape") toggleNavigation(false);
  if (event.key === "Tab") {
    const targets = [...sidebar.querySelectorAll("a,button")].filter((element) => element.getClientRects().length);
    const first = targets[0];
    const last = targets[targets.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
window.addEventListener("resize", () => {
  if (window.innerWidth > 850 && document.body.classList.contains("nav-open")) toggleNavigation(false);
});

const video = document.getElementById("hero-video");
const videoButton = document.getElementById("video-toggle");
if (video && videoButton) {
  function videoState() {
    videoButton.querySelector("span").textContent = video.paused ? "Play background" : "Pause background";
    videoButton.setAttribute("aria-pressed", String(!video.paused));
  }
  videoButton.addEventListener("click", async () => {
    if (video.paused) {
      try {
        await video.play();
      } catch {
        videoState();
      }
    } else video.pause();
  });
  video.addEventListener("play", videoState);
  video.addEventListener("pause", videoState);
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    video.play().catch(videoState);
  } else videoButton.hidden = true;
}
