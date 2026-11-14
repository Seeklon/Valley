/** Legacy screens remain available through the main navigation's tools menu. */
export async function openTool(page, name) {
  const menu = page.locator('.tools-menu');
  if (!(await menu.evaluate((element) => element.open))) await menu.locator('summary').click();
  await menu.getByRole('button', { name, exact: true }).click();
}
