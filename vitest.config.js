/* The Firebase side of the suite: security rules and Cloud Functions, run
   against the emulator. The Python suite is the app; this is the two things
   the app cannot test itself, because they run on somebody else's computer. */
export default {
  test: {
    include: ['tests/rules/**/*.test.js', 'tests/functions/**/*.test.js'],
    testTimeout: 20000,
    hookTimeout: 30000,
    fileParallelism: false,
  },
};
