import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import re
import os
import time
from datetime import datetime

# ================= 配置区 =================
CSV_FILE_PATH = r"C:\Users\wlh03\Desktop\AliMonitor\resultFC.csv"
TARGET_URL_KEYWORD = "manage_products" # 认准这个关键词
# =========================================

async def run():
    print(">>> 🚀 正在启动全量爬取 V3.0 (智能锁定版)...")
    
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            print(">>> ✅ 成功连接到浏览器！")
        except Exception as e:
            print(f">>> ❌ 连接失败: {e}")
            return

        context = browser.contexts[0]
        if not context.pages:
            print(">>> ❌ 浏览器没有打开任何页面！")
            return

        # ==========================================
        # 🔥 核心升级：自动寻找正确的标签页
        # ==========================================
        target_page = None
        print(f">>> 正在 {len(context.pages)} 个标签页中寻找阿里后台...")
        
        for p in context.pages:
            # 打印每个页面的标题，帮你排查问题
            try:
                title = await p.title()
                url = p.url
                print(f"    - 扫描标签页: [{title}]")
                
                if TARGET_URL_KEYWORD in url:
                    target_page = p
                    print("    >>> 🎯 找到了！就是这个窗口。")
                    break
            except: pass
        
        if not target_page:
            print(f">>> ❌ 未找到包含 '{TARGET_URL_KEYWORD}' 的页面。请确保你已经打开了阿里商品管理后台！")
            return
        
        # 激活该页面
        page = target_page
        await page.bring_to_front()
        # ==========================================

        # 0. 自动返回第一页
        print(">>> [准备] 检查是否在第一页...")
        try:
            btn_page_1 = page.locator('button[aria-label*="第1页"]')
            if await btn_page_1.count() == 0:
                btn_page_1 = page.locator('.next-pagination-list button').filter(has_text=re.compile(r"^1$"))
            if await btn_page_1.count() > 0:
                class_attr = await btn_page_1.get_attribute("class")
                if class_attr and "next-current" not in class_attr:
                    await btn_page_1.click()
                    print(">>> ✅ 已点击 [第1页]，等待重置...")
                    await page.wait_for_timeout(4000)
        except: pass

        # 1. 尝试切换到 50条/页
        print(">>> [准备] 切换到 [50条/页]...")
        try:
            btn_50 = page.locator(".next-pagination-size-selector-btn").filter(has_text="50")
            if await btn_50.count() > 0:
                await btn_50.click()
                print(">>> ✅ 已点击 [50] 按钮，等待刷新...")
                await page.wait_for_timeout(5000)
        except: pass

        all_items = []
        page_num = 1
        last_page_first_id = "" 
        
        # 2. 滚动逻辑 (万能模式)
        TARGET_CONTAINER = ".pp-layout-content"

        while True:
            print(f"\n>>> [第 {page_num} 页] 准备抓取...")

            try:
                # 等待商品出现
                await page.wait_for_selector('.list-item', state="attached", timeout=15000)
            except:
                print(">>> ⚠️ 等待超时：页面可能为空，尝试强制滚动...")

            # 确定滚动方式
            use_window_scroll = False
            if await page.locator(TARGET_CONTAINER).count() == 0:
                use_window_scroll = True
            else:
                try:
                    await page.evaluate(f"document.querySelector('{TARGET_CONTAINER}').scrollTop = 0")
                except: pass

            print("    >>> 正在扫描页面...")
            
            # === 滚动 ===
            if not use_window_scroll:
                try:
                    scroll_info = await page.evaluate(f"""() => {{
                        var el = document.querySelector('{TARGET_CONTAINER}');
                        return {{ scrollHeight: el.scrollHeight }};
                    }}""")
                    total_height = scroll_info['scrollHeight']
                    current_pos = 0
                    while current_pos < total_height:
                        current_pos += 600
                        await page.evaluate(f"document.querySelector('{TARGET_CONTAINER}').scrollTop = {current_pos}")
                        await page.wait_for_timeout(500) 
                        if len(await page.locator('.list-item').all()) >= 50: break
                except:
                    use_window_scroll = True
            
            if use_window_scroll:
                try:
                    total_height = await page.evaluate("document.body.scrollHeight")
                    current_pos = 0
                    while current_pos < total_height:
                        current_pos += 800
                        await page.evaluate(f"window.scrollTo(0, {current_pos})")
                        await page.wait_for_timeout(500)
                        total_height = await page.evaluate("document.body.scrollHeight")
                        if len(await page.locator('.list-item').all()) >= 50: break
                except Exception as e:
                    print(f">>> 全局滚动出错: {e}")

            await page.wait_for_timeout(1000)

            # === 解析数据 ===
            rows = await page.locator('.list-item').all()
            if len(rows) == 0:
                print(">>> ❌ 本页未获取到 .list-item，抓取停止。")
                print(">>> 调试提示：请确认页面上是否有商品？或者是否需要登录？")
                break

            # 翻页检测
            try:
                first_row_text = await rows[0].inner_text()
                id_match_check = re.search(r'ID:\s*(\d+)', first_row_text)
                current_first_id = id_match_check.group(1) if id_match_check else ""
                
                if page_num > 1 and current_first_id == last_page_first_id:
                    print(">>> ⚠️ 警告：ID未变，可能翻页失败")
                last_page_first_id = current_first_id
            except: pass
            
            current_page_items = []
            for row in rows:
                text_content = await row.inner_text()
                
                id_match = re.search(r'ID:\s*(\d+)', text_content)
                if not id_match: continue
                p_id = id_match.group(1)

                # 提取标题
                title = "未找到标题"
                link = ""
                subject_div = row.locator('.product-subject')
                if await subject_div.count() > 0:
                    a_tag = subject_div.locator('a').first
                    if await a_tag.count() > 0:
                        link = await a_tag.get_attribute('href')
                        if link and not link.startswith('http'): link = "https:" + link
                        pre_tag = a_tag.locator('pre')
                        if await pre_tag.count() > 0: title = await pre_tag.inner_text()
                        else: title = await a_tag.inner_text()
                title = title.strip()

                # 提取型号
                model = ""
                try:
                    model_el = row.locator('.product-model')
                    if await model_el.count() > 0:
                        raw_model = await model_el.inner_text()
                        model = raw_model.replace("型号:", "").replace("Model:", "").strip()
                except: pass

                # 提取其他
                price_val, owner_val, ali_time_val = "", "", ""
                try:
                    cols = await row.locator('.next-col').all()
                    if len(cols) >= 6:
                        price_val = await cols[3].inner_text()
                        owner_val = await cols[4].inner_text()
                        ali_time_val = await cols[5].inner_text()
                except: pass

                current_page_items.append({
                    'ID': p_id,
                    '型号': model,
                    '变化情况': '初始数据', 
                    'Ali更新时间': ali_time_val.strip(),
                    '商品链接': link,
                    '标题': title,
                    '价格': price_val.strip(),
                    '抓取时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    '负责人': owner_val.strip()
                })
            
            all_items.extend(current_page_items)
            print(f">>> [成功] 第 {page_num} 页抓取到: {len(current_page_items)} 条。")

            # === 翻页 ===
            try:
                next_btn = page.get_by_text("下一页", exact=True)
                if await next_btn.count() == 0:
                    print(">>> 无下一页按钮，爬取结束。")
                    break
                
                class_attr = await next_btn.get_attribute("class")
                if class_attr and "disabled" in class_attr:
                    print(">>> 翻页结束 (按钮禁用)。")
                    break

                await next_btn.click()
                print(">>> 点击下一页...")
                await page.wait_for_timeout(4000)
                page_num += 1
                
            except Exception as e:
                print(f">>> 翻页中止: {e}")
                break

        # === 保存 ===
        if all_items:
            df = pd.DataFrame(all_items)
            column_order = [
                'ID', '型号', '变化情况', 
                'Ali更新时间', 
                '商品链接', '标题', '价格', 
                '抓取时间', 
                '负责人'
            ]
            df = df[column_order]
            df.to_csv(CSV_FILE_PATH, index=False, encoding='utf-8-sig')
            print(f"\n>>> 🎉 全量爬取完成！共 {len(all_items)} 条数据。")
        else:
            print(">>> ❌ 未获取数据。")

if __name__ == '__main__':
    asyncio.run(run())