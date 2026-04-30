# Road Sign Practice

Static road sign quiz app generated from the local PDF tests.

## Run Locally

```powershell
python ab.py
```

## Build GitHub Pages Site

```powershell
python build_static_site.py
```

Publish the `docs` folder with GitHub Pages.

## Optional Google Sign-In

This app is ready for Firebase Google sign-in and Firestore profile sync.

1. Create a Firebase project on the free Spark plan.
2. Add a Web app in Firebase project settings.
3. Enable Authentication -> Google provider.
4. Add this authorized domain in Authentication settings:

```text
mrzain-ali.github.io
```

5. Create a Firestore database.
6. Use these Firestore rules:

```text
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /profiles/{userId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
  }
}
```

7. Replace the placeholder values in `static_site/firebase-config.js`, then run:

```powershell
python build_static_site.py
git add .
git commit -m "Enable Firebase sign in"
git push origin main
```
