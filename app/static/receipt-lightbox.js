(function () {
  let lightbox;
  let lightboxBody;

  function closeReceiptLightbox() {
    if (!lightbox) return;
    lightbox.classList.remove("on");
    lightbox.hidden = true;
    lightbox.setAttribute("aria-hidden", "true");
    if (lightboxBody) lightboxBody.innerHTML = "";
    document.body.classList.remove("lightbox-open");
  }

  function openReceiptLightbox(url, isImage, label) {
    if (!lightbox || !lightboxBody) return;
    lightboxBody.innerHTML = "";
    if (isImage) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = label || "Receipt";
      lightboxBody.appendChild(img);
    } else {
      const frame = document.createElement("iframe");
      frame.src = url;
      frame.title = label || "Receipt";
      lightboxBody.appendChild(frame);
    }
    lightbox.hidden = false;
    lightbox.setAttribute("aria-hidden", "false");
    lightbox.classList.add("on");
    document.body.classList.add("lightbox-open");
  }

  function bindReceiptThumbButtons(root) {
    const scope = root || document;
    scope.querySelectorAll(".receipt-thumb-btn").forEach((btn) => {
      if (btn.dataset.bound === "1") return;
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        openReceiptLightbox(
          btn.dataset.receiptUrl,
          btn.dataset.receiptImage === "1",
          btn.dataset.receiptLabel || "Receipt",
        );
      });
      btn.dataset.bound = "1";
    });
  }

  function init() {
    lightbox = document.getElementById("receipt-lightbox");
    lightboxBody = document.getElementById("receipt-lightbox-body");
    if (!lightbox) return;
    document.querySelectorAll("[data-close-lightbox]").forEach((el) => {
      el.addEventListener("click", closeReceiptLightbox);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && lightbox.classList.contains("on")) {
        closeReceiptLightbox();
      }
    });
    bindReceiptThumbButtons(document);
  }

  window.openReceiptLightbox = openReceiptLightbox;
  window.closeReceiptLightbox = closeReceiptLightbox;
  window.bindReceiptThumbButtons = bindReceiptThumbButtons;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
