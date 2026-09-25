// Confirm dangerous actions before their form is submitted.
document.addEventListener("submit", (event) => {
    const message = event.target.dataset.confirm;
    if (message && !confirm(message)) event.preventDefault();
}, true);

// Show only the settings that apply to the selected game type.
document.querySelectorAll(".game-form").forEach((form) => {
    const target = form.querySelector("input[name=target]");
    const placeholders = target ? JSON.parse(target.dataset.placeholders || "{}") : {};
    const update = () => {
        const type = (form.querySelector("input[name=type]:checked") || {}).value;
        form.querySelectorAll("[data-types]").forEach((field) => {
            field.hidden = !field.dataset.types.split(" ").includes(type);
        });
        if (target) form.querySelector(".target-hint").textContent = placeholders[type] || "";
    };
    form.addEventListener("change", update);
    update();
});

// Drop zones show the chosen files and highlight while dragging.
document.querySelectorAll(".dropzone").forEach((zone) => {
    const input = zone.querySelector("input[type=file]");
    const label = zone.querySelector(".dropzone-file");
    const show = () => {
        const names = Array.from(input.files).map((f) => f.name);
        label.textContent = names.length > 3 ? `${names.length} files selected` : names.join(", ");
        zone.classList.toggle("has-file", names.length > 0);
    };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach((e) => zone.addEventListener(e, () => zone.classList.add("dragging")));
    ["dragleave", "drop"].forEach((e) => zone.addEventListener(e, () => zone.classList.remove("dragging")));
    show();
});

// Big uploads: show a progress bar, then display the page the server redirects to.
document.querySelectorAll(".upload-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (event.defaultPrevented) return;
        event.preventDefault();
        const progress = form.querySelector(".progress");
        const bar = progress.querySelector(".progress-bar");
        const text = progress.querySelector(".progress-text");
        form.querySelectorAll("button").forEach((b) => (b.disabled = true));
        progress.hidden = false;

        const xhr = new XMLHttpRequest();
        xhr.open(form.method, form.action);
        xhr.upload.addEventListener("progress", (e) => {
            if (!e.lengthComputable) return;
            const pct = Math.round((e.loaded / e.total) * 100);
            bar.style.width = `${pct}%`;
            text.textContent = pct < 100 ? `Uploading… ${pct}%` : "Processing…";
        });
        xhr.addEventListener("load", () => {
            document.open();
            document.write(xhr.responseText);
            document.close();
            history.replaceState(null, "", xhr.responseURL);
        });
        xhr.addEventListener("error", () => {
            text.textContent = "Upload failed. Check your connection and try again.";
            form.querySelectorAll("button").forEach((b) => (b.disabled = false));
        });
        xhr.send(new FormData(form));
    });
});

// "Replace" buttons upload as soon as a file is picked.
document.querySelectorAll("input[data-autosubmit]").forEach((input) => {
    input.addEventListener("change", () => input.files.length && input.form.submit());
});

// Random beta keys.
document.querySelectorAll("[data-generate]").forEach((button) => {
    button.addEventListener("click", () => {
        const words = new Uint8Array(12);
        crypto.getRandomValues(words);
        const alphabet = "abcdefghjkmnpqrstuvwxyz23456789";
        const key = Array.from(words, (b) => alphabet[b % alphabet.length]).join("");
        document.getElementById(button.dataset.generate).value = `${key.slice(0, 4)}-${key.slice(4, 8)}-${key.slice(8)}`;
    });
});

// Sound previews: one plays at a time, click again to stop.
let playing = null;
document.querySelectorAll("[data-audio]").forEach((button) => {
    button.addEventListener("click", () => {
        const wasThis = playing && playing.button === button;
        if (playing) {
            playing.audio.pause();
            playing.button.classList.remove("playing");
            playing.button.textContent = "▶";
            playing = null;
        }
        if (wasThis) return;
        const audio = new Audio(button.dataset.audio);
        playing = { audio, button };
        button.classList.add("playing");
        button.textContent = "■";
        audio.addEventListener("ended", () => button.click());
        audio.play();
    });
});
