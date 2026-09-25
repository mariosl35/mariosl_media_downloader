const urlInput = document.getElementById("url-input");
const fetchBtn = document.getElementById("fetch-btn");

const previewCard = document.getElementById("info-card");
const previewThumb = document.getElementById("preview-thumb");
const previewDuration = document.getElementById("preview-duration");
const previewTitle = document.getElementById("preview-title");
const previewUploader = document.getElementById("preview-uploader");

const optionsCard = document.getElementById("options-card");
const pillVideo = document.getElementById("pill-video");
const pillAudio = document.getElementById("pill-audio");
const audioFormats = document.getElementById("audio-formats");
const qualityNote = document.getElementById("quality-note");

const downloadBtn = document.getElementById("download-btn");
const downloadBtnLabel = document.getElementById("download-btn-label");

const progressCard = document.getElementById("progress-card");
const progressStatus = document.getElementById("progress-status");
const progressPct = document.getElementById("progress-percent");
const progressBar = document.getElementById("progress-bar");

const doneCard = document.getElementById("complete-card");
const doneFilename = document.getElementById("complete-message");

const errorCard = document.getElementById("error-card");
const errorMsg = document.getElementById("error-message");

const formatOptions = document.querySelectorAll(".format-option");

let currentJobId = null;
let pollTimer = null;
let fetchTimeout = null;
let isDownloading = false;

let selectedType = "video";
let selectedAudioFormat = "mp3";

function showCard(card) {
    if (card) {
        card.classList.remove("hidden");
    }
}

function hideCard(card) {
    if (card) {
        card.classList.add("hidden");
    }
}

function resetDownloadState() {
    clearInterval(pollTimer);

    pollTimer = null;
    currentJobId = null;
    isDownloading = false;

    hideCard(previewCard);
    hideCard(optionsCard);
    hideCard(progressCard);
    hideCard(doneCard);
    hideCard(errorCard);

    setProgress(0);

    progressStatus.textContent = "Preparing...";

    downloadBtn.disabled = false;
    downloadBtnLabel.textContent = "Download";
}

function resetAll() {
    resetDownloadState();

    urlInput.value = "";

    previewThumb.src = "";
    previewThumb.alt = "";

    previewTitle.textContent = "—";
    previewUploader.textContent = "—";
    previewDuration.textContent = "—";

    selectedType = "video";
    selectedAudioFormat = "mp3";

    setDownloadType("video");
    setAudioFormat("mp3");
}

function setProgress(percent) {
    const value = Math.max(
        0,
        Math.min(100, Number(percent) || 0)
    );

    progressBar.style.width = `${value}%`;
    progressPct.textContent = `${Math.round(value)}%`;
}

function setDownloadType(type) {
    selectedType = type;

    const isVideo = type === "video";

    pillVideo.classList.toggle("active", isVideo);
    pillAudio.classList.toggle("active", !isVideo);

    pillVideo.setAttribute("aria-selected", String(isVideo));
    pillAudio.setAttribute("aria-selected", String(!isVideo));

    audioFormats.classList.toggle("hidden", isVideo);

    qualityNote.textContent = isVideo
        ? "Best available video quality · MP4"
        : `Audio extraction · ${selectedAudioFormat.toUpperCase()}`;

    downloadBtnLabel.textContent = isVideo
        ? "Download video"
        : "Download audio";
}

function setAudioFormat(format) {
    selectedAudioFormat = format;

    formatOptions.forEach((option) => {
        const active = option.dataset.format === format;

        option.classList.toggle("active", active);
    });

    if (selectedType === "audio") {
        qualityNote.textContent =
            `Audio extraction · ${format.toUpperCase()}`;
    }
}

async function fetchInfo() {
    const url = urlInput.value.trim();

    if (!url) {
        showError("Enter a media URL first.");
        return;
    }

    fetchBtn.disabled = true;
    fetchBtn.textContent = "Loading";

    hideCard(previewCard);
    hideCard(optionsCard);
    hideCard(progressCard);
    hideCard(doneCard);
    hideCard(errorCard);

    try {
        const response = await fetch("/api/info", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ url })
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            throw new Error(
                data.error || "Unable to fetch media information."
            );
        }

        previewThumb.src = data.thumbnail || "";
        previewThumb.alt = data.title || "Media thumbnail";

        previewTitle.textContent =
            data.title || "Unknown title";

        previewUploader.textContent =
            data.uploader || "Unknown uploader";

        previewDuration.textContent =
            data.duration || "Unknown";

        showCard(previewCard);
        showCard(optionsCard);

        previewCard.scrollIntoView({
            behavior: "smooth",
            block: "nearest"
        });
    } catch (error) {
        showError(error.message);
    } finally {
        fetchBtn.disabled = false;
        fetchBtn.textContent = "Fetch";
    }
}

async function startDownload() {
    if (isDownloading) {
        return;
    }

    const url = urlInput.value.trim();

    if (!url) {
        showError("Enter a media URL first.");
        return;
    }

    isDownloading = true;

    downloadBtn.disabled = true;
    downloadBtnLabel.textContent = "Starting";

    hideCard(doneCard);
    hideCard(errorCard);

    showCard(progressCard);

    setProgress(0);
    progressStatus.textContent = "Starting...";

    try {
        const response = await fetch("/api/download", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                url,
                download_type: selectedType,
                audio_format: selectedAudioFormat
            })
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            throw new Error(
                data.error || "Unable to start download."
            );
        }

        currentJobId = data.job_id;

        pollProgress();
    } catch (error) {
        isDownloading = false;

        downloadBtn.disabled = false;
        downloadBtnLabel.textContent =
            selectedType === "video"
                ? "Download video"
                : "Download audio";

        showError(error.message);
    }
}

function pollProgress() {
    clearInterval(pollTimer);

    pollTimer = setInterval(async () => {
        if (!currentJobId) {
            return;
        }

        try {
            const response = await fetch(
                `/api/progress/${encodeURIComponent(currentJobId)}`
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.error ||
                    "Unable to read download progress."
                );
            }

            const progress = Number(
                data.progress ?? data.percent ?? 0
            );

            setProgress(progress);

            progressStatus.textContent =
                data.status || "Downloading...";

            if (
                data.status === "complete" ||
                data.status === "completed"
            ) {
                finishDownload(data);
                return;
            }

            if (data.status === "error") {
                failDownload(
                    data.error || "Download failed."
                );
            }
        } catch (error) {
            failDownload(error.message);
        }
    }, 800);
}

function finishDownload(data) {
    clearInterval(pollTimer);

    pollTimer = null;
    isDownloading = false;

    setProgress(100);
    progressStatus.textContent = "Complete";

    downloadBtn.disabled = false;
    downloadBtnLabel.textContent =
        selectedType === "video"
            ? "Download video"
            : "Download audio";

    doneFilename.textContent =
        data.filename ||
        "Download completed.";

    showCard(doneCard);
}

function failDownload(message) {
    clearInterval(pollTimer);

    pollTimer = null;
    isDownloading = false;

    downloadBtn.disabled = false;
    downloadBtnLabel.textContent =
        selectedType === "video"
            ? "Download video"
            : "Download audio";

    showError(message);
}

function showError(message) {
    errorMsg.textContent =
        message || "Something went wrong.";

    showCard(errorCard);
    hideCard(doneCard);
}

/* TYPE SELECTION */

pillVideo.addEventListener("click", () => {
    setDownloadType("video");
});

pillAudio.addEventListener("click", () => {
    setDownloadType("audio");
});

/* AUDIO FORMAT SELECTION */

formatOptions.forEach((option) => {
    option.addEventListener("click", () => {
        setAudioFormat(option.dataset.format);
    });
});

/* FETCH */

fetchBtn.addEventListener("click", fetchInfo);

urlInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
        event.preventDefault();
        fetchInfo();
    }
});

/* DOWNLOAD */

downloadBtn.addEventListener("click", startDownload);

/* AUTOMATIC URL DETECTION */

urlInput.addEventListener("input", () => {
    clearTimeout(fetchTimeout);

    const value = urlInput.value.trim();

    if (!value.startsWith("http")) {
        return;
    }

    fetchTimeout = setTimeout(() => {
        fetchInfo();
    }, 600);
});

/* INITIAL STATE */

setDownloadType("video");
setAudioFormat("mp3");