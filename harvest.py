if __name__ == "__main__":
    try:
        main()  # your script's entrypoint
        print("✅ Harvester finished successfully")
    except Exception as e:
        import traceback, sys
        print("❌ Error:", str(e))
        traceback.print_exc()
        sys.exit(1)
