/* Optional end-to-end checks. Run against a local development server only. */
const {
  chromium
} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.env.BASE_URL || 'http://127.0.0.1:5000';
const output = path.resolve(process.env.BROWSER_ARTIFACTS || 'browser-artifacts');
const axePath = process.env.AXE_PATH || require.resolve('axe-core/axe.min.js');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(root).hostname)) {
  throw new Error('Browser checks create temporary data. Use a local development server.');
}
fs.mkdirSync(output, {
  recursive: true
});
const report = {
  workflows: [],
  audits: [],
  consoleErrors: [],
  pageErrors: [],
  overflow: []
};
const axeSource = fs.readFileSync(axePath, 'utf8');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
    args: ['--no-sandbox', ...JSON.parse(process.env.CHROMIUM_ARGS || '[]')]
  });
  const context = await browser.newContext({
    viewport: {
      width: 1440,
      height: 1000
    },
    reducedMotion: 'reduce'
  });
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') report.consoleErrors.push(message.text());
  });
  async function audit(label) {
    await page.evaluate(axeSource);
    const result = await page.evaluate(async () => {
      const data = await axe.run(document, {
        runOnly: {
          type: 'tag',
          values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']
        }
      });
      return data.violations.map(item => ({
        id: item.id,
        impact: item.impact,
        nodes: item.nodes.map(node => ({
          target: node.target,
          summary: node.failureSummary
        })).slice(0, 30)
      }));
    });
    report.audits.push({
      label,
      violations: result
    });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    if (overflow) report.overflow.push(label);
    await page.screenshot({
      path: path.join(output, label + '.png'),
      fullPage: true
    });
  }
  async function submit(name) {
    await Promise.all([page.waitForNavigation(), page.getByRole('button', {
      name,
      exact: true
    }).click()]);
  }
  async function createProject(title, status, category) {
    await page.goto(root + '/projects/new');
    await page.getByLabel('Project name', {
      exact: true
    }).fill(title);
    await page.getByLabel('What’s the idea?').fill('A thoughtful project with room to grow. Make the next small step clear, and keep all the useful details together.');
    await page.getByLabel('Category', {
      exact: true
    }).selectOption(category);
    await page.getByLabel('Status', {
      exact: true
    }).selectOption(status);
    await submit('Create project');
  }
  try {
    await page.goto(root);
    await audit('01-home-desktop');
    await page.setViewportSize({
      width: 390,
      height: 844
    });
    await audit('02-home-mobile');
    await page.setViewportSize({
      width: 1440,
      height: 1000
    });
    await page.goto(root + '/register');
    await audit('03-register-desktop');
    const suffix = Date.now().toString();
    const username = 'qa' + suffix;
    const email = username + '@example.test';
    const password = 'a thoughtful browser test passphrase';
    await page.getByLabel('First name', {
      exact: true
    }).fill('Alex');
    await page.getByLabel('Last name', {
      exact: true
    }).fill('Morgan');
    await page.getByLabel('Username', {
      exact: true
    }).fill(username);
    await page.getByLabel('Email address', {
      exact: true
    }).fill(email);
    await page.getByLabel('Password', {
      exact: true
    }).fill(password);
    await page.getByLabel('Confirm password', {
      exact: true
    }).fill(password);
    await submit('Create account');
    await page.getByRole('heading', {
      name: 'Hello, Alex.'
    }).waitFor();
    report.workflows.push('Registration and automatic sign-in');
    await audit('04-empty-workspace');
    await createProject('A brighter brand identity', 'in_progress', 'brand');
    const firstProject = page.url();
    for (const title of ['Collect inspiration', 'Explore three logo directions', 'Refine the final identity']) {
      await page.getByLabel('New checklist item').fill(title);
      await submit('Add item');
    }
    await Promise.all([page.waitForNavigation(), page.getByRole('checkbox', {
      name: 'Complete: Collect inspiration'
    }).click()]);
    assert.match(await page.locator('#checklist').innerText(), /1 of 3 done/);
    await audit('05-project-detail');
    report.workflows.push('Create project, add checklist items and complete an item');
    await page.getByRole('link', {
      name: 'Edit project',
      exact: true
    }).click();
    await page.getByLabel('A date to aim for').fill('2027-02-16');
    await submit('Save changes');
    assert.match(await page.locator('.project-snapshot').innerText(), /Feb 16, 2027/);
    await createProject('Portfolio, reimagined', 'in_progress', 'web');
    await createProject('Little ideas, big possibilities', 'idea', 'design');
    await createProject('The welcome collection', 'completed', 'design');
    await page.goto(root + '/dashboard');
    await audit('06-dashboard-desktop');
    await page.goto(root + '/projects');
    await audit('07-projects-desktop');
    await page.getByLabel('Search projects', {
      exact: true
    }).fill('Portfolio');
    await submit('Search projects');
    assert.equal(await page.locator('.project-card').count(), 1);
    report.workflows.push('Edit project and search/filter project collection');
    await page.goto(root + '/profile');
    await audit('08-profile-desktop');
    await page.getByLabel('First name', {
      exact: true
    }).fill('Alicia');
    await page.getByLabel('A little about you').fill('Making useful things, one idea at a time.');
    await submit('Save profile');
    assert.match(await page.locator('.profile-card').innerText(), /Alicia Morgan/);
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', {
      name: 'Export my workspace'
    }).click()]);
    assert.equal(download.suggestedFilename(), 'innovative-creations-workspace.json');
    report.workflows.push('Edit profile and download account export');
    await page.setViewportSize({
      width: 390,
      height: 844
    });
    await audit('09-profile-mobile');
    await page.goto(root + '/dashboard');
    await audit('10-dashboard-mobile');
    await page.getByRole('button', {
      name: 'Open menu',
      exact: true
    }).click();
    assert.equal(await page.getByRole('button', {
      name: 'Open menu',
      exact: true
    }).getAttribute('aria-expanded'), 'true');
    await page.getByRole('link', {
      name: 'My projects',
      exact: true
    }).click();
    await audit('11-projects-mobile');
    await page.setViewportSize({
      width: 320,
      height: 720
    });
    await audit('12-projects-small-mobile');
    await page.goto(root + '/projects/new');
    await audit('13-editor-small-mobile');
    await page.setViewportSize({
      width: 1440,
      height: 1000
    });
    await page.goto(firstProject);
    await page.getByRole('button', {
      name: 'Delete: Refine the final identity'
    }).click();
    await page.getByRole('button', {
      name: 'Keep it',
      exact: true
    }).click();
    assert.equal(await page.locator('.task-title').count(), 3);
    await page.getByRole('button', {
      name: 'Delete: Refine the final identity'
    }).click();
    await Promise.all([page.waitForNavigation(), page.getByRole('button', {
      name: 'Delete',
      exact: true
    }).click()]);
    assert.equal(await page.locator('.task-title').count(), 2);
    report.workflows.push('Mobile navigation and cancel/confirm destructive actions');
    await page.getByRole('button', {
      name: 'Log out',
      exact: true
    }).click();
    await page.goto(root + '/login');
    await audit('14-login-desktop');
    await page.getByLabel('Email or username', {
      exact: true
    }).fill(email);
    await page.getByLabel('Password', {
      exact: true
    }).fill(password);
    await submit('Log in');
    assert.match(await page.locator('h1').innerText(), /Hello, Alicia/);
    report.workflows.push('Logout and sign-in to persisted account');
    await page.goto(root + '/profile');
    await page.getByText('Close your account', {
      exact: true
    }).click();
    await page.getByLabel('Type your username: ' + username, {
      exact: true
    }).fill(username);
    await page.getByLabel('Current password', {
      exact: true
    }).last().fill(password);
    await page.getByRole('button', {
      name: 'Permanently delete my account'
    }).click();
    await Promise.all([page.waitForNavigation(), page.getByRole('button', {
      name: 'Delete',
      exact: true
    }).click()]);
    await page.goto(root + '/dashboard');
    assert.match(page.url(), /\/login/);
    report.workflows.push('Delete temporary test account and verify signed-out state');
  } finally {
    fs.writeFileSync(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  const violations = report.audits.reduce((sum, audit) => sum + audit.violations.length, 0);
  console.log(JSON.stringify({
    workflows: report.workflows,
    auditedPages: report.audits.length,
    accessibilityViolations: violations,
    overflow: report.overflow,
    pageErrors: report.pageErrors,
    consoleErrors: report.consoleErrors
  }));
  if (violations || report.overflow.length || report.pageErrors.length || report.consoleErrors.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
