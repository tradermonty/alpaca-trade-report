"""
ドキュメント自動修正スクリプト
低品質・未記載のドキュメントを自動改善
"""

import ast
import re
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

class DocstringFixer:
    def __init__(self):
        self.fixes_applied = 0
        
    def fix_file(self, file_path: Path) -> bool:
        """ファイルのドキュメントを修正"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            tree = ast.parse(content)
            
            # ファイル内の関数を収集して修正
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    content = self._fix_function_docstring(content, node, file_path)
                elif isinstance(node, ast.ClassDef):
                    content = self._fix_class_docstring(content, node, file_path)
            
            # 変更があった場合のみファイルを更新
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True
            
            return False
            
        except Exception as e:
            print(f"Error fixing {file_path}: {e}")
            return False
    
    def _fix_function_docstring(self, content: str, node: ast.FunctionDef, file_path: Path) -> str:
        """関数のドキュメントを修正"""
        lines = content.split('\n')
        
        # 既存のdocstringを取得
        existing_docstring = ast.get_docstring(node)
        
        if existing_docstring:
            # 既存ドキュメントの改善
            return self._improve_existing_docstring(content, node, existing_docstring)
        else:
            # 新規ドキュメントの追加
            return self._add_new_docstring(content, node, lines)
    
    def _fix_class_docstring(self, content: str, node: ast.ClassDef, file_path: Path) -> str:
        """クラスのドキュメントを修正"""
        existing_docstring = ast.get_docstring(node)
        
        if not existing_docstring and not node.name.startswith('_'):
            # クラス用の新規ドキュメントを生成
            new_docstring = self._generate_class_docstring(node)
            return self._insert_docstring_after_definition(content, node, new_docstring)
        
        return content
    
    def _improve_existing_docstring(self, content: str, node: ast.FunctionDef, existing_docstring: str) -> str:
        """既存ドキュメントを改善"""
        lines = content.split('\n')
        
        # 言語統一 (英語→日本語)
        improved_docstring = self._translate_to_japanese(existing_docstring)
        
        # Args/Returns の追加
        improved_docstring = self._add_missing_sections(improved_docstring, node)
        
        # 既存のdocstringを置換
        start_line = node.lineno
        for i, line in enumerate(lines[start_line:], start_line):
            if '"""' in line or "'''" in line:
                # docstringの範囲を特定して置換
                return self._replace_docstring_in_content(content, node, improved_docstring)
        
        return content
    
    def _add_new_docstring(self, content: str, node: ast.FunctionDef, lines: List[str]) -> str:
        """新規ドキュメントを追加"""
        if node.name.startswith('_'):
            return content  # プライベート関数はスキップ
        
        # 新しいdocstringを生成
        new_docstring = self._generate_function_docstring(node)
        
        # 関数定義の後に挿入
        return self._insert_docstring_after_definition(content, node, new_docstring)
    
    def _generate_function_docstring(self, node: ast.FunctionDef) -> str:
        """関数用のドキュメントを生成"""
        # 関数名から推測される機能
        function_purpose = self._infer_function_purpose(node.name)
        
        docstring_parts = [f'    """', f'    {function_purpose}']
        
        # Args セクション
        if node.args.args:
            docstring_parts.append('')
            docstring_parts.append('    Args:')
            for arg in node.args.args:
                if arg.arg != 'self':
                    arg_desc = self._infer_arg_description(arg.arg)
                    docstring_parts.append(f'        {arg.arg}: {arg_desc}')
        
        # Returns セクション
        has_return = any(isinstance(n, ast.Return) for n in ast.walk(node))
        if has_return:
            docstring_parts.append('')
            docstring_parts.append('    Returns:')
            return_desc = self._infer_return_description(node.name)
            docstring_parts.append(f'        {return_desc}')
        
        docstring_parts.append('    """')
        
        return '\n'.join(docstring_parts)
    
    def _generate_class_docstring(self, node: ast.ClassDef) -> str:
        """クラス用のドキュメントを生成"""
        class_purpose = self._infer_class_purpose(node.name)
        
        return f'''    """
    {class_purpose}
    
    このクラスは{node.name}の機能を提供します。
    """'''
    
    def _infer_function_purpose(self, function_name: str) -> str:
        """関数名から目的を推測"""
        name_lower = function_name.lower()
        
        if name_lower.startswith('get_'):
            return f"{function_name.replace('get_', '')}を取得"
        elif name_lower.startswith('set_'):
            return f"{function_name.replace('set_', '')}を設定"
        elif name_lower.startswith('is_'):
            return f"{function_name.replace('is_', '')}かどうかを判定"
        elif name_lower.startswith('has_'):
            return f"{function_name.replace('has_', '')}を持っているかを確認"
        elif name_lower.startswith('create_'):
            return f"{function_name.replace('create_', '')}を作成"
        elif name_lower.startswith('update_'):
            return f"{function_name.replace('update_', '')}を更新"
        elif name_lower.startswith('delete_'):
            return f"{function_name.replace('delete_', '')}を削除"
        elif name_lower.startswith('calculate_'):
            return f"{function_name.replace('calculate_', '')}を計算"
        elif name_lower.startswith('execute_'):
            return f"{function_name.replace('execute_', '')}を実行"
        elif name_lower.startswith('analyze_'):
            return f"{function_name.replace('analyze_', '')}を分析"
        elif name_lower.startswith('process_'):
            return f"{function_name.replace('process_', '')}を処理"
        elif 'trade' in name_lower or 'trading' in name_lower:
            return "取引処理を実行"
        elif 'order' in name_lower:
            return "注文処理を実行"
        elif 'config' in name_lower:
            return "設定を管理"
        elif 'monitor' in name_lower:
            return "監視処理を実行"
        elif 'validate' in name_lower:
            return "妥当性を検証"
        else:
            return f"{function_name}を実行"
    
    def _infer_class_purpose(self, class_name: str) -> str:
        """クラス名から目的を推測"""
        name_lower = class_name.lower()
        
        if 'strategy' in name_lower:
            return "取引戦略を管理するクラス"
        elif 'config' in name_lower:
            return "設定を管理するクラス"
        elif 'manager' in name_lower:
            return "管理機能を提供するクラス"
        elif 'client' in name_lower:
            return "APIクライアント機能を提供するクラス"
        elif 'monitor' in name_lower:
            return "監視機能を提供するクラス"
        elif 'executor' in name_lower:
            return "実行機能を提供するクラス"
        elif 'analyzer' in name_lower:
            return "分析機能を提供するクラス"
        elif 'calculator' in name_lower:
            return "計算機能を提供するクラス"
        elif 'adapter' in name_lower:
            return "アダプター機能を提供するクラス"
        elif 'interface' in name_lower:
            return "インターフェースを定義するクラス"
        else:
            return f"{class_name}の機能を提供するクラス"
    
    def _infer_arg_description(self, arg_name: str) -> str:
        """引数名から説明を推測"""
        name_lower = arg_name.lower()
        
        if 'symbol' in name_lower:
            return "取引銘柄シンボル"
        elif 'price' in name_lower:
            return "価格"
        elif 'qty' in name_lower or 'quantity' in name_lower:
            return "数量"
        elif 'size' in name_lower:
            return "サイズ"
        elif 'rate' in name_lower:
            return "レート"
        elif 'config' in name_lower:
            return "設定オブジェクト"
        elif 'data' in name_lower:
            return "データ"
        elif 'file' in name_lower:
            return "ファイルパス"
        elif 'url' in name_lower:
            return "URL"
        elif 'key' in name_lower:
            return "キー"
        elif 'value' in name_lower:
            return "値"
        elif 'timeout' in name_lower:
            return "タイムアウト時間"
        elif 'retries' in name_lower:
            return "リトライ回数"
        elif arg_name in ['self', 'cls']:
            return "インスタンス" if arg_name == 'self' else "クラス"
        else:
            return f"{arg_name}パラメータ"
    
    def _infer_return_description(self, function_name: str) -> str:
        """関数名から戻り値の説明を推測"""
        name_lower = function_name.lower()
        
        if name_lower.startswith('is_') or name_lower.startswith('has_'):
            return "bool: 条件を満たす場合True"
        elif name_lower.startswith('get_'):
            return f"{function_name.replace('get_', '')}の値"
        elif name_lower.startswith('calculate_'):
            return "float: 計算結果"
        elif name_lower.startswith('create_'):
            return "作成されたオブジェクト"
        elif 'list' in name_lower:
            return "List: リスト形式のデータ"
        elif 'dict' in name_lower:
            return "Dict: 辞書形式のデータ"
        else:
            return "実行結果"
    
    def _translate_to_japanese(self, docstring: str) -> str:
        """英語のドキュメントを日本語に変換"""
        # 簡易的な英日変換辞書
        translations = {
            'Args:': '引数:',
            'Arguments:': '引数:',
            'Parameters:': 'パラメータ:',
            'Returns:': '戻り値:',
            'Return:': '戻り値:',
            'Raises:': '例外:',
            'Example:': '例:',
            'Examples:': '例:',
            'Note:': '注意:',
            'Notes:': '注意:',
        }
        
        result = docstring
        for en, jp in translations.items():
            result = result.replace(en, jp)
        
        return result
    
    def _add_missing_sections(self, docstring: str, node: ast.FunctionDef) -> str:
        """不足しているセクションを追加"""
        lines = docstring.split('\n')
        
        # Args セクションが不足している場合
        if node.args.args and not re.search(r'(Args?|引数|パラメータ):', docstring):
            # Args セクションを追加
            lines.append('')
            lines.append('    引数:')
            for arg in node.args.args:
                if arg.arg != 'self':
                    arg_desc = self._infer_arg_description(arg.arg)
                    lines.append(f'        {arg.arg}: {arg_desc}')
        
        # Returns セクションが不足している場合
        has_return = any(isinstance(n, ast.Return) for n in ast.walk(node))
        if has_return and not re.search(r'(Returns?|戻り値|返り値):', docstring):
            lines.append('')
            lines.append('    戻り値:')
            return_desc = self._infer_return_description(node.name)
            lines.append(f'        {return_desc}')
        
        return '\n'.join(lines)
    
    def _insert_docstring_after_definition(self, content: str, node, new_docstring: str) -> str:
        """定義の後にドキュメントを挿入"""
        lines = content.split('\n')
        
        # 関数/クラス定義行を見つける
        def_line = node.lineno - 1  # 0ベースのインデックス
        
        # 定義行の後に挿入
        lines.insert(def_line + 1, new_docstring)
        
        self.fixes_applied += 1
        return '\n'.join(lines)
    
    def _replace_docstring_in_content(self, content: str, node, new_docstring: str) -> str:
        """既存のドキュメントを置換"""
        # 簡略化された実装
        # 実際の実装では、docstringの正確な位置を特定して置換
        return content  # 現在は変更なし

def fix_priority_files():
    """優先度の高いファイルを修正"""
    priority_files = [
        'api_clients.py',
        'config.py', 
        'orb.py',
        'trading_interfaces.py',
        'common_constants.py'
    ]
    
    fixer = DocstringFixer()
    
    print("🔧 高優先度ファイルのドキュメント修正を開始...")
    
    for filename in priority_files:
        file_path = SRC_DIR / filename
        if file_path.exists():
            print(f"Processing {filename}...", end=" ")
            if fixer.fix_file(file_path):
                print("✅ 修正完了")
            else:
                print("➖ 変更なし")
        else:
            print(f"⚠️  {filename} が見つかりません")
    
    print(f"\n✅ 修正完了: {fixer.fixes_applied}件のドキュメントを改善")

def main():
    """メイン処理"""
    print("📝 ドキュメント自動修正を開始...")
    
    # 優先度の高いファイルのみを修正
    fix_priority_files()
    
    print("\n📋 次のステップ:")
    print("1. 修正されたファイルの内容を確認")
    print("2. 必要に応じて手動で詳細を追加")  
    print("3. 残りのファイルの段階的修正")
    print("4. ドキュメント品質の再分析")

if __name__ == "__main__":
    main()