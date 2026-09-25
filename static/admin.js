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
// Forms with data-chunked send their file in pieces first, so any size gets through Cloudflare.
function sendRequest(method, url, body, headers = {}, onProgress = null) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(method, url);
        Object.entries(headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));
        if (onProgress) xhr.upload.addEventListener("progress", (e) => onProgress(e.loaded));
        xhr.addEventListener("load", () => {
            let data = {};
            try { data = JSON.parse(xhr.responseText); } catch (e) { /* HTML page */ }
            resolve({ status: xhr.status, data, xhr });
        });
        xhr.addEventListener("error", () => reject(new Error("network")));
        xhr.addEventListener("timeout", () => reject(new Error("timeout")));
        xhr.send(body);
    });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function uploadInChunks(form, file, report) {
    const csrf = { "X-CSRF-Token": form.querySelector("input[name=csrf]").value };
    const start = await sendRequest("POST", form.dataset.chunked,
        JSON.stringify({ filename: file.name, size: file.size }), { ...csrf, "Content-Type": "application/json" });
    if (start.status !== 200) throw new Error(start.data.error || `The server refused the upload (${start.status}).`);
    const url = `${form.dataset.chunked}/${start.data.id}`;
    const chunkSize = start.data.chunk_size;

    let offset = 0;
    let failures = 0;
    while (offset < file.size) {
        const piece = file.slice(offset, offset + chunkSize);
        let response = null;
        try {
            response = await sendRequest("POST", `${url}?offset=${offset}`, piece,
                { ...csrf, "Content-Type": "application/octet-stream" }, (loaded) => report(offset + loaded, file.size));
        } catch (e) { /* dropped connection: retry below */ }
        if (response && (response.status === 200 || response.status === 409)) {
            // 409 means the server has a different amount than we thought; carry on from there.
            offset = response.data.received;
            failures = 0;
            continue;
        }
        if (response && response.status < 500 && ![408, 429].includes(response.status)) {
            throw new Error(response.data.error || `Upload failed (${response.status}).`);
        }
        if (++failures > 6) throw new Error("Upload failed after several retries. Check your connection and try again.");
        report(offset, file.size, `Connection problem, retrying (${failures}/6)…`);
        await sleep(2000 * failures);
        try {
            const status = await sendRequest("GET", url, null);
            if (status.status === 200) offset = status.data.received;
            else if (status.status === 404) throw new Error(status.data.error || "The upload expired. Start it again.");
        } catch (e) {
            if (e.message !== "network" && e.message !== "timeout") throw e;
        }
    }
    return { id: start.data.id, cancel: () => sendRequest("DELETE", url, null, csrf).catch(() => {}) };
}

document.querySelectorAll(".upload-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
        if (event.defaultPrevented) return;
        event.preventDefault();
        const progress = form.querySelector(".progress");
        const bar = progress.querySelector(".progress-bar");
        const text = progress.querySelector(".progress-text");
        const buttons = form.querySelectorAll("button");
        buttons.forEach((b) => (b.disabled = true));
        progress.hidden = false;
        const report = (loaded, total, message) => {
            const pct = total ? Math.min(100, Math.round((loaded / total) * 100)) : 100;
            bar.style.width = `${pct}%`;
            text.textContent = message || (pct < 100 ? `Uploading… ${pct}%` : "Processing…");
        };
        const fail = (message) => {
            window.onbeforeunload = null;
            text.textContent = message;
            buttons.forEach((b) => (b.disabled = false));
        };
        const showResult = (xhr) => {
            window.onbeforeunload = null;
            document.open();
            document.write(xhr.responseText);
            document.close();
            history.replaceState(null, "", xhr.responseURL);
        };

        const body = new FormData(form);
        const fileInput = form.querySelector("input[type=file]");
        const file = fileInput && fileInput.files[0];
        window.onbeforeunload = () => "The upload is still running.";
        try {
            if (form.dataset.chunked && file) {
                const upload = await uploadInChunks(form, file, report);
                body.delete(fileInput.name);
                body.append("upload_id", upload.id);
                report(file.size, file.size, "Processing…");
                const done = await sendRequest("POST", form.action, body).catch(() => null);
                if (!done) { upload.cancel(); return fail("Upload failed while finishing. Try again."); }
                return showResult(done.xhr);
            }
            const done = await sendRequest("POST", form.action, body, {}, (loaded) => report(loaded, file ? file.size : 0));
            showResult(done.xhr);
        } catch (error) {
            fail(error.message === "network" ? "Upload failed. Check your connection and try again." : error.message);
        }
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
