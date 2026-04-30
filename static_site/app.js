const STORAGE_KEY = "road-sign-practice-profile-v2";
const FIREBASE_SDK_VERSION = "10.12.5";

const app = {
  mode: "random",
  questions: [],
  questionById: new Map(),
  tests: [],
  sequence: [],
  index: 0,
  answered: false,
  session: { correct: 0, wrong: 0, answered: 0 },
  profile: { attempts: [] },
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
  modeButtons: Array.from(document.querySelectorAll("[data-mode]")),
  questionnaireControls: document.getElementById("questionnaire-controls"),
  testSelect: document.getElementById("test-select"),
  setSelect: document.getElementById("set-select"),
  startButton: document.getElementById("start-button"),
  modeLabel: document.getElementById("mode-label"),
  positionLabel: document.getElementById("position-label"),
  statusLabel: document.getElementById("status-label"),
  questionView: document.getElementById("question-view"),
  emptyView: document.getElementById("empty-view"),
  emptyTitle: document.getElementById("empty-title"),
  emptyMessage: document.getElementById("empty-message"),
  questionTitle: document.getElementById("question-title"),
  questionMeta: document.getElementById("question-meta"),
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

function loadLocalProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return normalizeProfile(parsed);
  } catch {
    return { attempts: [] };
  }
}

function saveLocalProfile() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(normalizeProfile(app.profile)));
}

function normalizeProfile(profile) {
  const attempts = Array.isArray(profile.attempts) ? profile.attempts : [];
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
      .slice(-1000)
  };
}

function mergeProfiles(first, second) {
  const merged = new Map();
  for (const attempt of normalizeProfile(first).attempts) {
    merged.set(attempt.id, attempt);
  }
  for (const attempt of normalizeProfile(second).attempts) {
    merged.set(attempt.id, attempt);
  }
  return {
    attempts: Array.from(merged.values())
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
      .slice(-1000)
  };
}

function profileStats() {
  const attempts = normalizeProfile(app.profile).attempts;
  const correct = attempts.filter((attempt) => attempt.result === "correct").length;
  const wrong = attempts.filter((attempt) => attempt.result === "wrong").length;
  const total = correct + wrong;
  const accuracy = total ? Math.round((correct / total) * 100) : 0;
  return { correct, wrong, total, accuracy };
}

function latestMistakeIds() {
  const seen = new Set();
  const ids = [];
  for (const attempt of normalizeProfile(app.profile).attempts.slice().reverse()) {
    if (attempt.result !== "wrong" || seen.has(attempt.question_id)) {
      continue;
    }
    if (app.questionById.has(attempt.question_id)) {
      seen.add(attempt.question_id);
      ids.push(attempt.question_id);
    }
  }
  return ids;
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
  els.profileName.textContent = "Guest profile";
  els.profileEmail.textContent = app.firebaseEnabled
    ? "Sign in to sync progress"
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

function updateSessionUi() {
  els.positionLabel.textContent = `${Math.min(app.index + 1, app.sequence.length)} / ${app.sequence.length}`;
  const bits = [];
  if (app.session.answered) {
    bits.push(`Session: ${app.session.correct} correct, ${app.session.wrong} wrong`);
  }
  if (app.user && app.authReady) {
    bits.push("Cloud sync on");
  }
  els.statusLabel.textContent = bits.join(" | ");
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

function setMode(mode) {
  app.mode = mode;
  els.modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  els.questionnaireControls.hidden = mode !== "questionnaire";
  els.modeLabel.textContent = {
    random: "Random",
    questionnaire: "Questionnaire",
    mistakes: "Mistakes"
  }[mode];
  startSession();
}

function startSession() {
  app.session = { correct: 0, wrong: 0, answered: 0 };
  app.index = 0;
  app.answered = false;

  if (app.mode === "random") {
    app.sequence = shuffle(app.questions.map((question) => question.id));
  } else if (app.mode === "questionnaire") {
    const testName = els.testSelect.value;
    const setNo = Number(els.setSelect.value);
    app.sequence = sortedQuestions(
      app.questions.filter(
        (question) => question.test === testName && question.questionnaire === setNo
      )
    ).map((question) => question.id);
  } else {
    app.sequence = latestMistakeIds();
  }

  renderCurrent();
}

function showEmpty(title, message) {
  els.questionView.hidden = true;
  els.emptyView.hidden = false;
  els.emptyTitle.textContent = title;
  els.emptyMessage.textContent = message;
  els.positionLabel.textContent = `0 / ${app.sequence.length}`;
  updateSessionUi();
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
  updateProfileUi();
  if (!app.sequence.length) {
    const empty = app.mode === "mistakes"
      ? ["No mistakes yet", "Wrong answers will appear here after practice."]
      : ["No questions", "Choose another practice mode."];
    showEmpty(empty[0], empty[1]);
    return;
  }

  const question = app.questionById.get(app.sequence[app.index]);
  if (!question) {
    showEmpty("Missing question", "This question could not be loaded.");
    return;
  }

  els.questionView.hidden = false;
  els.emptyView.hidden = true;
  els.questionTitle.textContent = question.description;
  els.questionMeta.textContent =
    `${question.test} | Set ${question.questionnaire} | Q${question.question} | Page ${question.page_number}`;
  els.questionImage.src = question.image_url;
  resetQuestionControls();
  updateSessionUi();
}

async function syncCloudProfile() {
  if (!app.firebase || !app.user) {
    return;
  }

  const { doc, setDoc } = app.firebase.firestore;
  const ref = doc(app.firebase.db, "profiles", app.user.uid);
  await setDoc(ref, {
    displayName: app.user.displayName || "",
    email: app.user.email || "",
    photoURL: app.user.photoURL || "",
    attempts: normalizeProfile(app.profile).attempts,
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
  const cloudProfile = snapshot.exists() ? snapshot.data() : { attempts: [] };
  app.profile = mergeProfiles(app.profile, cloudProfile);
  saveLocalProfile();
  await syncCloudProfile();
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

  app.profile = mergeProfiles(app.profile, { attempts: [attempt] });
  saveLocalProfile();
  updateProfileUi();

  try {
    await syncCloudProfile();
  } catch (error) {
    els.statusLabel.textContent = "Saved on this device. Cloud sync failed.";
  }
}

async function submitAnswer() {
  if (app.answered) {
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
  els.feedback.textContent = isCorrect
    ? `Correct. Actual answer: ${question.correct_answer}.`
    : `Wrong. Actual answer: ${question.correct_answer}.`;

  els.answerForm.querySelectorAll("input").forEach((input) => {
    input.disabled = true;
  });
  els.submitButton.disabled = true;
  els.nextButton.disabled = false;
  els.nextButton.textContent =
    app.index + 1 >= app.sequence.length ? "Summary" : "Next";
  updateSessionUi();
}

function showSummary() {
  const total = app.session.answered;
  const percent = total ? Math.round((app.session.correct / total) * 100) : 0;
  els.questionView.hidden = true;
  els.emptyView.hidden = false;
  els.emptyTitle.textContent = "Session complete";
  els.emptyMessage.textContent =
    `${app.session.correct}/${total} correct (${percent}%).`;
  updateSessionUi();
}

function nextQuestion() {
  if (app.index + 1 >= app.sequence.length) {
    showSummary();
    return;
  }
  app.index += 1;
  renderCurrent();
}

function showNotice(message) {
  els.feedback.hidden = false;
  els.feedback.className = "feedback notice";
  els.feedback.textContent = message;
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
      } catch {
        els.statusLabel.textContent = "Signed in. Cloud profile could not load.";
      }
    }
    updateProfileUi();
    if (app.mode === "mistakes") {
      startSession();
    }
  });
}

async function handleAuthClick() {
  if (!app.firebaseEnabled || !app.firebase) {
    showNotice("Google sign-in is ready in the app code. Add Firebase config to turn it on.");
    return;
  }

  const { authApi, auth, provider } = app.firebase;
  if (app.user) {
    await authApi.signOut(auth);
    app.user = null;
    updateProfileUi();
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
  startSession();
}

els.modeButtons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

els.testSelect.addEventListener("change", () => {
  populateSetSelect();
  if (app.mode === "questionnaire") {
    startSession();
  }
});

els.setSelect.addEventListener("change", () => {
  if (app.mode === "questionnaire") {
    startSession();
  }
});

els.startButton.addEventListener("click", startSession);
els.authButton.addEventListener("click", handleAuthClick);
els.answerForm.addEventListener("change", () => {
  if (!app.answered) {
    els.submitButton.disabled = !selectedAnswer();
  }
});
els.submitButton.addEventListener("click", submitAnswer);
els.nextButton.addEventListener("click", nextQuestion);

init().catch((error) => {
  showEmpty("Could not start", error.message);
  els.bankCount.textContent = "Question bank unavailable";
});
