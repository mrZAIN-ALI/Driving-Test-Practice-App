const STORAGE_KEY = "road-sign-practice-profile-v2";
const FIREBASE_SDK_VERSION = "10.12.5";
const MAX_ATTEMPTS = 500;

const app = {
  mode: "random",
  questions: [],
  questionById: new Map(),
  tests: [],
  sequence: [],
  index: 0,
  answered: false,
  sessionState: "idle",
  session: { correct: 0, wrong: 0, answered: 0, total: 0, startedAt: "" },
  profile: { attempts: [], draft: null },
  authReady: false,
  firebaseEnabled: false,
  firebase: null,
  user: null
};

const els = {
  bankCount: document.getElementById("bank-count"),
  profilePhoto: document.getElementById("profile-photo"),
  profileInitials: document.getElementById("profile-initials"),
  profileName: document.getElementById("profile-name"),
  profileEmail: document.getElementById("profile-email"),
  authButton: document.getElementById("auth-button"),
  statCorrect: document.getElementById("stat-correct"),
  statWrong: document.getElementById("stat-wrong"),
  statAccuracy: document.getElementById("stat-accuracy"),
  statReview: document.getElementById("stat-review"),
  modeButtons: Array.from(document.querySelectorAll("[data-mode]")),
  questionnaireControls: document.getElementById("questionnaire-controls"),
  testSelect: document.getElementById("test-select"),
  setSelect: document.getElementById("set-select"),
  startButton: document.getElementById("start-button"),
  resumeButton: document.getElementById("resume-button"),
  saveExitButton: document.getElementById("save-exit-button"),
  mobileSaveButton: document.getElementById("mobile-save-button"),
  modeLabel: document.getElementById("mode-label"),
  positionLabel: document.getElementById("position-label"),
  statusLabel: document.getElementById("status-label"),
  sessionScore: document.getElementById("session-score"),
  sessionMeterFill: document.getElementById("session-meter-fill"),
  questionView: document.getElementById("question-view"),
  emptyView: document.getElementById("empty-view"),
  emptyKicker: document.getElementById("empty-kicker"),
  emptyTitle: document.getElementById("empty-title"),
  emptyMessage: document.getElementById("empty-message"),
  questionTitle: document.getElementById("question-title"),
  questionMeta: document.getElementById("question-meta"),
  questionCount: document.getElementById("question-count"),
  questionImage: document.getElementById("question-image"),
  answerForm: document.getElementById("answer-form"),
  feedback: document.getElementById("feedback"),
  submitButton: document.getElementById("submit-button"),
  nextButton: document.getElementById("next-button")
};

function createId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeDraft(draft) {
  if (!draft || !Array.isArray(draft.sequence) || !draft.sequence.length) {
    return null;
  }

  return {
    id: draft.id || createId(),
    savedAt: draft.savedAt || new Date().toISOString(),
    mode: ["random", "questionnaire", "mistakes"].includes(draft.mode) ? draft.mode : "random",
    selectedTest: draft.selectedTest || "",
    selectedSet: Number(draft.selectedSet || 1),
    sequence: draft.sequence.filter((id) => typeof id === "string"),
    index: Math.max(0, Number(draft.index || 0)),
    session: normalizeSession(draft.session)
  };
}

function normalizeSession(session) {
  return {
    correct: Number(session?.correct || 0),
    wrong: Number(session?.wrong || 0),
    answered: Number(session?.answered || 0),
    total: Number(session?.total || 0),
    startedAt: session?.startedAt || new Date().toISOString()
  };
}

function normalizeProfile(profile) {
  const attempts = Array.isArray(profile?.attempts) ? profile.attempts : [];
  return {
    attempts: attempts
      .filter((attempt) => attempt && attempt.question_id)
      .map((attempt) => ({
        id: attempt.id || createId(),
        timestamp: attempt.timestamp || new Date().toISOString(),
        mode: attempt.mode || "practice",
        question_id: attempt.question_id,
        test: attempt.test || "",
        questionnaire: Number(attempt.questionnaire || 0),
        question: Number(attempt.question || 0),
        description: attempt.description || "",
        selected_answer: String(attempt.selected_answer || ""),
        correct_answer: String(attempt.correct_answer || ""),
        result: attempt.result === "correct" ? "correct" : "wrong"
      }))
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
      .slice(-MAX_ATTEMPTS),
    draft: normalizeDraft(profile?.draft)
  };
}

function loadLocalProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return normalizeProfile(raw ? JSON.parse(raw) : {});
  } catch {
    return { attempts: [], draft: null };
  }
}

function saveLocalProfile() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(normalizeProfile(app.profile)));
}

function mergeProfiles(first, second) {
  const merged = new Map();
  for (const attempt of normalizeProfile(first).attempts) {
    merged.set(attempt.id, attempt);
  }
  for (const attempt of normalizeProfile(second).attempts) {
    merged.set(attempt.id, attempt);
  }

  const firstDraft = normalizeProfile(first).draft;
  const secondDraft = normalizeProfile(second).draft;
  let draft = firstDraft || secondDraft;
  if (firstDraft && secondDraft) {
    draft = new Date(secondDraft.savedAt) > new Date(firstDraft.savedAt)
      ? secondDraft
      : firstDraft;
  }

  return {
    attempts: Array.from(merged.values())
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
      .slice(-MAX_ATTEMPTS),
    draft
  };
}

function mistakeSummaries() {
  const summaries = new Map();
  for (const attempt of normalizeProfile(app.profile).attempts) {
    if (!app.questionById.has(attempt.question_id)) {
      continue;
    }

    const current = summaries.get(attempt.question_id) || {
      id: attempt.question_id,
      wrong: 0,
      correct: 0,
      lastResult: "",
      lastTime: ""
    };

    if (attempt.result === "wrong") {
      current.wrong += 1;
    } else {
      current.correct += 1;
    }
    current.lastResult = attempt.result;
    current.lastTime = attempt.timestamp;
    summaries.set(attempt.question_id, current);
  }

  return Array.from(summaries.values());
}

function reviewMistakeIds() {
  const summaries = mistakeSummaries().filter((item) => item.wrong > 0);
  const unresolved = summaries.filter((item) => item.lastResult === "wrong");
  const pool = unresolved.length ? unresolved : summaries;

  return pool
    .sort((a, b) => {
      if (a.lastResult !== b.lastResult) {
        return a.lastResult === "wrong" ? -1 : 1;
      }
      if (b.wrong !== a.wrong) {
        return b.wrong - a.wrong;
      }
      return new Date(b.lastTime) - new Date(a.lastTime);
    })
    .map((item) => item.id);
}

function profileStats() {
  const attempts = normalizeProfile(app.profile).attempts;
  const correct = attempts.filter((attempt) => attempt.result === "correct").length;
  const wrong = attempts.filter((attempt) => attempt.result === "wrong").length;
  const total = correct + wrong;
  return {
    correct,
    wrong,
    total,
    accuracy: total ? Math.round((correct / total) * 100) : 0,
    review: reviewMistakeIds().length
  };
}

function initialsFromName(name) {
  const cleaned = String(name || "Guest").trim();
  const parts = cleaned.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0] || "").join("").toUpperCase() || "G";
}

function updateProfileUi() {
  const stats = profileStats();
  els.statCorrect.textContent = stats.correct;
  els.statWrong.textContent = stats.wrong;
  els.statAccuracy.textContent = `${stats.accuracy}%`;
  els.statReview.textContent = stats.review;

  if (app.user) {
    const name = app.user.displayName || "Signed in";
    els.profileName.textContent = name;
    els.profileEmail.textContent = app.user.email || "Google profile";
    els.profileInitials.textContent = initialsFromName(name);
    if (app.user.photoURL) {
      els.profilePhoto.src = app.user.photoURL;
      els.profilePhoto.hidden = false;
      els.profileInitials.hidden = true;
    } else {
      els.profilePhoto.hidden = true;
      els.profileInitials.hidden = false;
    }
    els.authButton.textContent = "Sign out";
    return;
  }

  els.profilePhoto.hidden = true;
  els.profileInitials.hidden = false;
  els.profileInitials.textContent = "G";
  els.profileName.textContent = "Guest mode";
  els.profileEmail.textContent = app.firebaseEnabled
    ? "Sign in to sync profile"
    : "Progress stays on this device";
  els.authButton.textContent = app.firebaseEnabled ? "Sign in" : "Guest";
}

function sortedQuestions(questions) {
  return questions.slice().sort((a, b) => (
    a.test.localeCompare(b.test) ||
    a.questionnaire - b.questionnaire ||
    a.question - b.question
  ));
}

function shuffle(values) {
  const copy = values.slice();
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function buildSequence(mode = app.mode) {
  if (mode === "random") {
    return shuffle(app.questions.map((question) => question.id));
  }

  if (mode === "questionnaire") {
    const testName = els.testSelect.value;
    const setNo = Number(els.setSelect.value);
    return sortedQuestions(
      app.questions.filter(
        (question) => question.test === testName && question.questionnaire === setNo
      )
    ).map((question) => question.id);
  }

  return reviewMistakeIds();
}

function modeName(mode = app.mode) {
  return {
    random: "Random",
    questionnaire: "Questionnaire",
    mistakes: "Mistakes"
  }[mode];
}

function setStatus(message) {
  els.statusLabel.textContent = message || "";
}

function updateSessionUi() {
  const total = app.sessionState === "active"
    ? app.sequence.length
    : buildSequence(app.mode).length;
  const position = app.sessionState === "active" && total
    ? `${Math.min(app.index + 1, total)} / ${total}`
    : `0 / ${total}`;
  const answered = app.session.answered || 0;
  const meter = total ? Math.round((answered / total) * 100) : 0;

  els.modeLabel.textContent = modeName();
  els.positionLabel.textContent = position;
  els.sessionScore.textContent = `${app.session.correct || 0} correct`;
  els.sessionMeterFill.style.width = `${meter}%`;

  const active = app.sessionState === "active";
  els.startButton.hidden = active;
  els.saveExitButton.hidden = !active;
  els.mobileSaveButton.hidden = !active;
  els.resumeButton.hidden = active || !app.profile.draft;

  els.modeButtons.forEach((button) => {
    button.disabled = active && button.dataset.mode !== app.mode;
    button.classList.toggle("active", button.dataset.mode === app.mode);
  });

  els.testSelect.disabled = active;
  els.setSelect.disabled = active;
  updateProfileUi();
}

function populateSelectors() {
  els.testSelect.innerHTML = "";
  for (const test of app.tests) {
    const option = document.createElement("option");
    option.value = test.name;
    option.textContent = test.name;
    els.testSelect.appendChild(option);
  }
  populateSetSelect();
}

function populateSetSelect() {
  const selectedTest = app.tests.find((test) => test.name === els.testSelect.value);
  els.setSelect.innerHTML = "";
  if (!selectedTest) {
    return;
  }

  for (const setNo of selectedTest.questionnaires) {
    const option = document.createElement("option");
    option.value = String(setNo);
    option.textContent = `Questionnaire ${setNo}`;
    els.setSelect.appendChild(option);
  }
}

function showEmpty(kicker, title, message) {
  els.questionView.hidden = true;
  els.emptyView.hidden = false;
  els.emptyKicker.textContent = kicker;
  els.emptyTitle.textContent = title;
  els.emptyMessage.textContent = message;
  updateSessionUi();
}

function showReady(message) {
  app.sessionState = "idle";
  app.sequence = [];
  app.index = 0;
  app.answered = false;
  app.session = { correct: 0, wrong: 0, answered: 0, total: 0, startedAt: "" };

  const count = buildSequence(app.mode).length;
  const title = app.mode === "mistakes"
    ? "Review the signs you missed"
    : app.mode === "questionnaire"
      ? "Start the selected questionnaire"
      : "Start a fresh random round";
  const fallback = count
    ? `${count} questions ready.`
    : app.mode === "mistakes"
      ? "No review questions yet. Wrong answers will appear here."
      : "No questions found for this mode.";

  showEmpty(modeName(), title, message || fallback);
  setStatus(message || "Ready");
}

function selectedAnswer() {
  const checked = els.answerForm.querySelector("input[name='answer']:checked");
  return checked ? checked.value : "";
}

function resetQuestionControls() {
  app.answered = false;
  els.answerForm.reset();
  els.answerForm.querySelectorAll("input").forEach((input) => {
    input.disabled = false;
  });
  els.feedback.hidden = true;
  els.feedback.className = "feedback";
  els.feedback.textContent = "";
  els.submitButton.disabled = true;
  els.nextButton.disabled = true;
  els.nextButton.textContent = "Next";
}

function renderCurrent() {
  if (app.sessionState !== "active") {
    showReady();
    return;
  }

  if (!app.sequence.length) {
    showReady("No questions are available for this mode.");
    return;
  }

  const question = app.questionById.get(app.sequence[app.index]);
  if (!question) {
    showReady("This saved question no longer exists.");
    return;
  }

  els.questionView.hidden = false;
  els.emptyView.hidden = true;
  els.questionTitle.textContent = question.description;
  els.questionMeta.textContent =
    `${question.test} | Set ${question.questionnaire} | Q${question.question} | Page ${question.page_number}`;
  els.questionCount.textContent = String(question.question);
  els.questionImage.src = question.image_url;
  resetQuestionControls();
  updateSessionUi();
  setStatus(app.user ? "Cloud sync on" : "Guest progress saved on this device");
}

async function syncCloudProfile() {
  if (!app.firebase || !app.user) {
    return;
  }

  const { doc, setDoc } = app.firebase.firestore;
  const ref = doc(app.firebase.db, "profiles", app.user.uid);
  const profile = normalizeProfile(app.profile);
  await setDoc(ref, {
    displayName: app.user.displayName || "",
    email: app.user.email || "",
    photoURL: app.user.photoURL || "",
    attempts: profile.attempts,
    draft: profile.draft,
    updatedAt: new Date().toISOString()
  }, { merge: true });
}

async function loadCloudProfile(user) {
  if (!app.firebase || !user) {
    return;
  }

  const { doc, getDoc } = app.firebase.firestore;
  const ref = doc(app.firebase.db, "profiles", user.uid);
  const snapshot = await getDoc(ref);
  const cloudProfile = snapshot.exists() ? snapshot.data() : { attempts: [], draft: null };
  app.profile = mergeProfiles(app.profile, cloudProfile);
  saveLocalProfile();
  await syncCloudProfile();
}

async function persistProfile() {
  app.profile = normalizeProfile(app.profile);
  saveLocalProfile();
  updateProfileUi();
  try {
    await syncCloudProfile();
  } catch {
    setStatus("Saved locally. Cloud sync failed.");
  }
}

async function recordAttempt(question, selected, isCorrect) {
  const attempt = {
    id: createId(),
    timestamp: new Date().toISOString(),
    mode: app.mode,
    question_id: question.id,
    test: question.test,
    questionnaire: question.questionnaire,
    question: question.question,
    description: question.description,
    selected_answer: selected,
    correct_answer: question.correct_answer,
    result: isCorrect ? "correct" : "wrong"
  };

  app.profile = mergeProfiles(app.profile, { attempts: [attempt], draft: app.profile.draft });
  await persistProfile();
}

function startSession() {
  if (app.sessionState === "active") {
    setStatus("Save & Exit before starting another session.");
    return;
  }

  const sequence = buildSequence(app.mode);
  if (!sequence.length) {
    showReady(app.mode === "mistakes"
      ? "No mistakes to review right now."
      : "No questions are available for this selection.");
    return;
  }

  app.profile.draft = null;
  saveLocalProfile();
  app.sessionState = "active";
  app.sequence = sequence;
  app.index = 0;
  app.answered = false;
  app.session = {
    correct: 0,
    wrong: 0,
    answered: 0,
    total: sequence.length,
    startedAt: new Date().toISOString()
  };
  renderCurrent();
}

async function saveAndExit() {
  if (app.sessionState !== "active") {
    return;
  }

  const nextIndex = app.answered ? app.index + 1 : app.index;
  if (nextIndex >= app.sequence.length) {
    app.profile.draft = null;
    await persistProfile();
    showSummary();
    return;
  }

  app.profile.draft = {
    id: createId(),
    savedAt: new Date().toISOString(),
    mode: app.mode,
    selectedTest: els.testSelect.value,
    selectedSet: Number(els.setSelect.value || 1),
    sequence: app.sequence,
    index: nextIndex,
    session: app.session
  };
  await persistProfile();
  showReady("Session saved. Resume when you are ready.");
}

function restoreQuestionnaireSelection(draft) {
  if (draft.selectedTest) {
    els.testSelect.value = draft.selectedTest;
    populateSetSelect();
  }
  if (draft.selectedSet) {
    els.setSelect.value = String(draft.selectedSet);
  }
}

function resumeSession() {
  const draft = normalizeDraft(app.profile.draft);
  if (!draft) {
    showReady("No saved session found.");
    return;
  }

  const sequence = draft.sequence.filter((id) => app.questionById.has(id));
  if (!sequence.length) {
    app.profile.draft = null;
    saveLocalProfile();
    showReady("Saved session could not be restored.");
    return;
  }

  app.mode = draft.mode;
  if (app.mode === "questionnaire") {
    restoreQuestionnaireSelection(draft);
  }
  els.questionnaireControls.hidden = app.mode !== "questionnaire";
  app.sessionState = "active";
  app.sequence = sequence;
  app.index = Math.min(draft.index, sequence.length - 1);
  app.answered = false;
  app.session = {
    ...draft.session,
    total: sequence.length
  };
  renderCurrent();
}

async function submitAnswer() {
  if (app.sessionState !== "active" || app.answered) {
    return;
  }

  const answer = selectedAnswer();
  if (!answer) {
    return;
  }

  const question = app.questionById.get(app.sequence[app.index]);
  const isCorrect = answer === question.correct_answer;
  app.answered = true;
  app.session.answered += 1;
  if (isCorrect) {
    app.session.correct += 1;
  } else {
    app.session.wrong += 1;
  }

  await recordAttempt(question, answer, isCorrect);

  els.feedback.hidden = false;
  els.feedback.classList.add(isCorrect ? "correct" : "wrong");
  if (app.mode === "mistakes") {
    els.feedback.textContent = isCorrect
      ? `Correct. Removed from review. Actual answer: ${question.correct_answer}.`
      : `Wrong. Still in review. Actual answer: ${question.correct_answer}.`;
  } else {
    els.feedback.textContent = isCorrect
      ? `Correct. Actual answer: ${question.correct_answer}.`
      : `Wrong. Actual answer: ${question.correct_answer}.`;
  }

  els.answerForm.querySelectorAll("input").forEach((input) => {
    input.disabled = true;
  });
  els.submitButton.disabled = true;
  els.nextButton.disabled = false;
  els.nextButton.textContent =
    app.index + 1 >= app.sequence.length ? "Summary" : "Next";
  updateSessionUi();
}

async function showSummary() {
  const total = app.session.answered;
  const percent = total ? Math.round((app.session.correct / total) * 100) : 0;
  app.sessionState = "finished";
  app.profile.draft = null;
  await persistProfile();
  els.questionView.hidden = true;
  els.emptyView.hidden = false;
  els.emptyKicker.textContent = "Finished";
  els.emptyTitle.textContent = `${app.session.correct}/${total} correct`;
  els.emptyMessage.textContent = `${percent}% accuracy. Mistakes stay in review until you answer them correctly.`;
  setStatus("Session complete");
  app.sequence = [];
  app.index = 0;
  app.sessionState = "idle";
  updateSessionUi();
}

function nextQuestion() {
  if (app.sessionState !== "active") {
    return;
  }

  if (app.index + 1 >= app.sequence.length) {
    showSummary();
    return;
  }
  app.index += 1;
  renderCurrent();
}

function showNotice(message) {
  setStatus(message);
  if (!els.questionView.hidden) {
    els.feedback.hidden = false;
    els.feedback.className = "feedback notice";
    els.feedback.textContent = message;
  } else {
    els.emptyMessage.textContent = message;
  }
}

function setMode(mode) {
  if (app.sessionState === "active") {
    showNotice("Save & Exit before changing modes.");
    return;
  }

  app.mode = mode;
  els.questionnaireControls.hidden = mode !== "questionnaire";
  showReady();
}

async function initFirebase() {
  const config = window.ROAD_SIGN_FIREBASE_CONFIG;
  app.firebaseEnabled = Boolean(
    config &&
    config.enabled &&
    config.firebase &&
    config.firebase.apiKey &&
    config.firebase.authDomain &&
    config.firebase.projectId &&
    config.firebase.appId
  );

  if (!app.firebaseEnabled) {
    app.authReady = true;
    updateProfileUi();
    return;
  }

  const [firebaseApp, firebaseAuth, firebaseFirestore] = await Promise.all([
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_SDK_VERSION}/firebase-app.js`),
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_SDK_VERSION}/firebase-auth.js`),
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_SDK_VERSION}/firebase-firestore.js`)
  ]);

  const firebaseInstance = firebaseApp.initializeApp(config.firebase);
  const auth = firebaseAuth.getAuth(firebaseInstance);
  const db = firebaseFirestore.getFirestore(firebaseInstance);
  const provider = new firebaseAuth.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });

  app.firebase = {
    auth,
    db,
    provider,
    authApi: firebaseAuth,
    firestore: firebaseFirestore
  };

  firebaseAuth.getRedirectResult(auth).catch(() => {});
  firebaseAuth.onAuthStateChanged(auth, async (user) => {
    app.user = user;
    app.authReady = true;
    if (user) {
      try {
        await loadCloudProfile(user);
        if (app.sessionState !== "active") {
          showReady("Signed in. Profile sync is on.");
        }
      } catch {
        setStatus("Signed in. Cloud profile could not load.");
      }
    }
    updateProfileUi();
    updateSessionUi();
  });
}

async function handleAuthClick() {
  if (!app.firebaseEnabled || !app.firebase) {
    showNotice("Google sign-in is not configured yet.");
    return;
  }

  const { authApi, auth, provider } = app.firebase;
  if (app.user) {
    await authApi.signOut(auth);
    app.user = null;
    updateProfileUi();
    showReady("Signed out. Guest progress remains on this device.");
    return;
  }

  const isPhone = window.matchMedia("(max-width: 760px)").matches;
  try {
    if (isPhone) {
      await authApi.signInWithRedirect(auth, provider);
    } else {
      await authApi.signInWithPopup(auth, provider);
    }
  } catch {
    await authApi.signInWithRedirect(auth, provider);
  }
}

async function loadQuestionBank() {
  const response = await fetch("./data/questions.json");
  if (!response.ok) {
    throw new Error("Question bank could not load.");
  }

  const data = await response.json();
  app.questions = sortedQuestions(data.questions);
  app.questionById = new Map(app.questions.map((question) => [question.id, question]));
  app.tests = data.tests;
  els.bankCount.textContent = `${app.questions.length} questions from ${app.tests.length} PDFs`;
  populateSelectors();
}

async function init() {
  app.profile = loadLocalProfile();
  updateProfileUi();
  await loadQuestionBank();
  await initFirebase();
  showReady();
}

els.modeButtons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

els.testSelect.addEventListener("change", () => {
  if (app.sessionState === "active") {
    return;
  }
  populateSetSelect();
  showReady();
});

els.setSelect.addEventListener("change", () => {
  if (app.sessionState !== "active") {
    showReady();
  }
});

els.startButton.addEventListener("click", startSession);
els.resumeButton.addEventListener("click", resumeSession);
els.saveExitButton.addEventListener("click", saveAndExit);
els.mobileSaveButton.addEventListener("click", saveAndExit);
els.authButton.addEventListener("click", handleAuthClick);
els.answerForm.addEventListener("change", () => {
  if (app.sessionState === "active" && !app.answered) {
    els.submitButton.disabled = !selectedAnswer();
  }
});
els.submitButton.addEventListener("click", submitAnswer);
els.nextButton.addEventListener("click", nextQuestion);

init().catch((error) => {
  showEmpty("Error", "Could not start", error.message);
  els.bankCount.textContent = "Question bank unavailable";
});
