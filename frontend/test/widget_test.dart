import 'package:flutter_test/flutter_test.dart';

import 'package:automated_trading_system_ui/main.dart';

void main() {
  testWidgets('Indian ATS dashboard loads correctly',
      (WidgetTester tester) async {
    await tester.pumpWidget(const ATSApp());

    // Verify key UI elements
    expect(find.text('ATS Terminal'), findsOneWidget);
    expect(find.text('EQUITY'), findsOneWidget);
    expect(find.text('RELIANCE'), findsOneWidget);
  });
}
